import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAccountShell } from '../../hooks/useAccountShell'
import { getJsonCached, invalidateCache } from '../../lib/apiCache'
import { pLimit } from '../../lib/concurrency'
import type { Consultation, CustomEntry, ExamEvent, Lesson, UpcomingEvent } from '../../types'
import { addWeekdays, isoDate, nearestWeekday, weekdayDates } from '../../ui/dateFormat'

export const WEEKDAY_LABELS = ['Пн', 'Вт', 'Ср', 'Чт', 'Пт']
export const DAY_FULL_NAMES = ['Понедельник', 'Вторник', 'Среда', 'Четверг', 'Пятница']

export interface CustomEntryFields {
  subject: string
  teacher: string
  room: string
  timeFrom: string
  timeTo: string
  period: string
}

/** Своя запись — часть Расписания, не отдельная лента (явная просьба
 * пользователя 15 сентября 2026: раньше показывалась только в
 * "Консультации на неделе", он хотел её прямо в самом расписании). Отсюда
 * и проекция в форму Lesson — тот же тип, что и настоящие уроки EduPage,
 * просто с `custom: true` и `id` для удаления, чтобы WeekGrid/LessonList
 * рисовали её тем же кодом, без отдельной ветки на каждый компонент. */
export function customEntryToLesson(e: CustomEntry): Lesson {
  return {
    period: e.period,
    start: e.time_from,
    end: e.time_to,
    subject: e.subject,
    teachers: e.teacher ? [e.teacher] : [],
    classrooms: e.room ? [e.room] : [],
    is_cancelled: false,
    id: e.id,
    custom: true,
  }
}

/** Настоящие уроки уже приходят от EduPage отсортированными по периоду;
 * свои записи вставляем в тот же порядок — по номеру урока, а без него (у
 * записи только время, без периода) — в конец списка по времени начала. */
export function mergeLessons(real: Lesson[] | null, custom: Lesson[]): Lesson[] | null {
  if (real === null && custom.length === 0) return null
  return [...(real ?? []), ...custom].sort((a, b) => {
    const pa = a.period ?? 999
    const pb = b.period ?? 999
    if (pa !== pb) return pa - pb
    return (a.start ?? '99:99').localeCompare(b.start ?? '99:99')
  })
}

/** Номера уроков, занятых любым не отменённым уроком — настоящим ИЛИ уже
 * добавленной своей записью (живой случай 16 сентября 2026: два "чилл"
 * поставили на 9 и 10 уроки, а кнопки этих же номеров при повторном
 * открытии формы оставались активны — свои записи не считались занятостью
 * вовсе). Отменённый настоящий урок по-прежнему НЕ считается занятым:
 * именно в его освободившийся слот чаще всего и хочется поставить что-то
 * своё (см. живой случай с "Military Training" 15 сентября 2026). */
export function occupiedPeriodsOf(lessons: Lesson[] | null): number[] {
  return (lessons ?? []).filter((l) => !l.is_cancelled && l.period != null).map((l) => l.period as number)
}

/** СОР/СОЧ/БЖБ конкретного урока — по совпадению даты и названия предмета
 * (оба в итоге приходят из одного справочника EduPage Subjects, см.
 * edupage.py::_resolve_subject, так что точное совпадение — рабочий
 * критерий). Своя запись предмета в справочнике EduPage нет — не матчим. */
export function examBadgeFor(exams: ExamEvent[] | null, dateIso: string, subject: string): ExamEvent | null {
  if (!exams) return null
  const norm = subject.trim().toLowerCase()
  return exams.find((e) => e.event_date === dateIso && e.subject_name?.trim().toLowerCase() === norm) ?? null
}

/** Данные Расписания: неделя целиком (для вида "Неделя"), выбранный день
 * (для вида "Список", листается независимо от недели — см. addWeekdays),
 * консультации на неделю и ближайшие события. Четыре независимых источника,
 * тот же принцип честных пустых состояний, что и на Главной. */
export function useScheduleData() {
  const shell = useAccountShell()
  const [dayOffset, setDayOffset] = useState(0)
  const [weekOffset, setWeekOffset] = useState(0)
  const [view, setView] = useState<'list' | 'grid'>('grid')

  const [weekLessons, setWeekLessons] = useState<(Lesson[] | null)[] | null>(null)
  const [weekConsultations, setWeekConsultations] = useState<(Consultation[] | null)[] | null>(null)
  const [selectedLessons, setSelectedLessons] = useState<Lesson[] | null>(null)
  const [events, setEvents] = useState<UpcomingEvent[] | null>(null)
  const [exams, setExams] = useState<ExamEvent[] | null>(null)
  const [loadingWeek, setLoadingWeek] = useState(true)
  const [loadingDay, setLoadingDay] = useState(true)
  const [loadingEvents, setLoadingEvents] = useState(true)
  const [refreshing, setRefreshing] = useState(false)

  // Модалка «Добавить» — дата (ISO-строка), для которой она открыта, не
  // day-of-week индекс: грид всегда в терминах текущей недели (week[dow]),
  // а список может пролистать на день вне её (dayOffset без ограничений) —
  // общий знаменатель у обоих один и тот же, сама дата.
  const [addModalDateIso, setAddModalDateIso] = useState<string | null>(null)
  const [addError, setAddError] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)

  const today = new Date()
  // На выходных показываем не только что закончившуюся неделю, а
  // ближайшую предстоящую (с понедельника) — просьба пользователя
  // 16 сентября 2026: иначе сетка в субботу/воскресенье показывала бы
  // неделю, которая уже прошла целиком, без единого актуального дня.
  //
  // Мемо, а не голое выражение (как selectedDate ниже) — намеренно:
  // weekOffset теперь двигает week, а loadWeek()/refresh() зависят от
  // week как от объекта (не только от ISO-строк, как examsFromIso ниже),
  // так что его ссылка обязана быть стабильной между рендерами, где
  // weekOffset не менялся, иначе эффект ниже перезапускался бы бесконечно.
  const week = useMemo(() => {
    const base = nearestWeekday(new Date())
    base.setDate(base.getDate() + weekOffset * 7)
    return weekdayDates(base)
  }, [weekOffset])
  const selectedDate = addWeekdays(nearestWeekday(today), dayOffset)

  // Один заход на Расписание — это 11 отдельных запросов к EduPage (5 дней
  // расписания + 5 дней замен/консультаций + ближайшие события), каждый
  // со своим логином/сессией на бэкенде. Без ограничения все 11 летят
  // одновременно и на практике иногда роняют EduPage в мусорные ответы
  // (см. lib/concurrency.ts). Общий на всю неделю лимитер — не по три на
  // группу, а именно на всё сразу, иначе с событиями всё равно набегает
  // 3+3+1=7 одновременных. Свои записи (custom-entries) — не EduPage, но
  // тот же лимитер, чтобы не плодить отдельную волну параллельных запросов.
  const limit = useMemo(() => pLimit(3), [])

  // Диапазон для бейджа «есть СОР» — объединение видимой недели грида и
  // выбранного дня списка (может гулять за пределы недели через
  // prevDay/nextDay). ISO-строки, не объекты Date — иначе эффект ниже
  // перезапускался бы на каждый рендер (week/selectedDate — новые ссылки
  // всякий раз, см. week = weekdayDates(...) выше).
  const examsFromIso = isoDate(selectedDate < week[0] ? selectedDate : week[0])
  const examsToIso = isoDate(selectedDate > week[4] ? selectedDate : week[4])

  const loadWeek = useCallback(async () => {
    setLoadingWeek(true)
    const [lessons, cons, custom] = await Promise.all([
      Promise.all(week.map((d) => limit(() => getJsonCached<Lesson[]>(`/api/schedule/today?date=${isoDate(d)}`)))),
      Promise.all(week.map((d) => limit(() => getJsonCached<Consultation[]>(`/api/consultations?date=${isoDate(d)}`)))),
      Promise.all(week.map((d) => limit(() => getJsonCached<CustomEntry[]>(`/api/custom-entries?date=${isoDate(d)}`)))),
    ])
    setWeekLessons(lessons.map((l, i) => mergeLessons(l, (custom[i] ?? []).map(customEntryToLesson))))
    setWeekConsultations(cons)
    setLoadingWeek(false)
  }, [limit, week])

  const loadSelectedDay = useCallback(async () => {
    setLoadingDay(true)
    const [lessons, custom] = await Promise.all([
      limit(() => getJsonCached<Lesson[]>(`/api/schedule/today?date=${isoDate(selectedDate)}`)),
      limit(() => getJsonCached<CustomEntry[]>(`/api/custom-entries?date=${isoDate(selectedDate)}`)),
    ])
    setSelectedLessons(mergeLessons(lessons, (custom ?? []).map(customEntryToLesson)))
    setLoadingDay(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dayOffset, limit])

  useEffect(() => {
    limit(() => getJsonCached<UpcomingEvent[]>('/api/events/upcoming?limit=8')).then((e) => {
      setEvents(e)
      setLoadingEvents(false)
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [limit])

  useEffect(() => {
    loadWeek()
  }, [loadWeek])

  useEffect(() => {
    loadSelectedDay()
  }, [loadSelectedDay])

  useEffect(() => {
    limit(() => getJsonCached<ExamEvent[]>(`/api/schedule/exams?from=${examsFromIso}&to=${examsToIso}`)).then(
      setExams,
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [examsFromIso, examsToIso, limit])

  // Кэш ответов на клиенте живёт час (см. lib/apiCache.ts — сделано
  // нарочно, чтобы не дёргать СУШ/EduPage на каждое переключение вкладки),
  // но иногда реально нужно увидеть свежее прямо сейчас (заменили урок
  // только что) — кнопка «Обновить» в углу обходит кэш точечно на эту
  // неделю, не трогая час для всего остального приложения. Не сбрасывает
  // loadingWeek/loadingDay/loadingEvents в true — старые данные остаются
  // на экране, пока не придут новые, вместо мигания скелетоном.
  const refresh = useCallback(async () => {
    setRefreshing(true)
    const [lessons, cons, custom, dayLessons, dayCustom, ev, ex] = await Promise.all([
      Promise.all(
        week.map((d) =>
          limit(() => getJsonCached<Lesson[]>(`/api/schedule/today?date=${isoDate(d)}`, { force: true })),
        ),
      ),
      Promise.all(
        week.map((d) =>
          limit(() => getJsonCached<Consultation[]>(`/api/consultations?date=${isoDate(d)}`, { force: true })),
        ),
      ),
      Promise.all(
        week.map((d) =>
          limit(() => getJsonCached<CustomEntry[]>(`/api/custom-entries?date=${isoDate(d)}`, { force: true })),
        ),
      ),
      limit(() => getJsonCached<Lesson[]>(`/api/schedule/today?date=${isoDate(selectedDate)}`, { force: true })),
      limit(() => getJsonCached<CustomEntry[]>(`/api/custom-entries?date=${isoDate(selectedDate)}`, { force: true })),
      limit(() => getJsonCached<UpcomingEvent[]>('/api/events/upcoming?limit=8', { force: true })),
      limit(() =>
        getJsonCached<ExamEvent[]>(`/api/schedule/exams?from=${examsFromIso}&to=${examsToIso}`, { force: true }),
      ),
    ])
    setWeekLessons(lessons.map((l, i) => mergeLessons(l, (custom[i] ?? []).map(customEntryToLesson))))
    setWeekConsultations(cons)
    setSelectedLessons(mergeLessons(dayLessons, (dayCustom ?? []).map(customEntryToLesson)))
    setEvents(ev)
    setExams(ex)
    setRefreshing(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [week, selectedDate, examsFromIso, examsToIso, limit])

  // Отличаем "источник недоступен" (все дни null) от "честно пусто" (все
  // дни успешно пришли, просто без консультаций) — иначе непривязанный
  // EduPage молча выглядел бы как "консультаций нет", а не как ошибка.
  const consultationsUnavailable = weekConsultations !== null && weekConsultations.every((d) => d === null)
  const consultationsFlat = consultationsUnavailable
    ? null
    : (weekConsultations ?? []).flatMap((day, i) => (day ?? []).map((c) => ({ ...c, dow: i })))

  function openAddModal(date: Date) {
    setAddError(null)
    setAddModalDateIso(isoDate(date))
  }
  function closeAddModal() {
    setAddModalDateIso(null)
    setAddError(null)
  }

  async function submitCustomEntry(fields: CustomEntryFields) {
    if (addModalDateIso === null) return
    const subject = fields.subject.trim()
    if (!subject) {
      setAddError('Укажи предмет')
      return
    }
    setAdding(true)
    setAddError(null)
    const period = fields.period.trim() ? Number(fields.period.trim()) : null
    const res = await fetch('/api/custom-entries', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        entry_date: addModalDateIso,
        subject,
        teacher: fields.teacher.trim() || null,
        room: fields.room.trim() || null,
        time_from: fields.timeFrom || null,
        time_to: fields.timeTo || null,
        period,
      }),
    })
    const body = await res.json().catch(() => ({}))
    setAdding(false)
    if (!res.ok) {
      setAddError(body.detail ?? `Не получилось добавить (${res.status})`)
      return
    }
    invalidateCache('/api/custom-entries')
    const lesson = customEntryToLesson(body as CustomEntry)
    const dow = week.findIndex((d) => isoDate(d) === addModalDateIso)
    if (dow !== -1) {
      setWeekLessons((prev) =>
        prev ? prev.map((day, i) => (i === dow ? mergeLessons(day, [lesson]) : day)) : prev,
      )
    }
    if (isoDate(selectedDate) === addModalDateIso) {
      setSelectedLessons((prev) => mergeLessons(prev, [lesson]))
    }
    closeAddModal()
  }

  async function deleteCustomEntry(id: string) {
    setWeekLessons((prev) => prev?.map((day) => day?.filter((l) => l.id !== id) ?? day) ?? prev)
    setSelectedLessons((prev) => prev?.filter((l) => l.id !== id) ?? prev)
    const res = await fetch(`/api/custom-entries/${id}`, { method: 'DELETE', credentials: 'same-origin' })
    invalidateCache('/api/custom-entries')
    if (!res.ok) {
      await loadWeek() // не удалилось — вернуть как было
      await loadSelectedDay()
    }
  }

  return {
    ...shell,
    view,
    setView,
    dayOffset,
    prevDay: () => setDayOffset((o) => o - 1),
    nextDay: () => setDayOffset((o) => o + 1),
    weekOffset,
    prevWeek: () => setWeekOffset((o) => o - 1),
    nextWeek: () => setWeekOffset((o) => o + 1),
    thisWeek: () => setWeekOffset(0),
    week,
    weekLessons,
    selectedDate,
    selectedLessons,
    exams,
    consultations: consultationsFlat,
    events,
    loadingWeek,
    loadingDay,
    loadingEvents,
    refreshing,
    refresh,
    addModalDateIso,
    openAddModal,
    closeAddModal,
    submitCustomEntry,
    deleteCustomEntry,
    adding,
    addError,
  }
}

export type ScheduleData = ReturnType<typeof useScheduleData>
