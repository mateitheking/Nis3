import { useCallback, useEffect, useState } from 'react'
import { useAccountShell } from '../../hooks/useAccountShell'
import { getJsonCached, invalidateCache } from '../../lib/apiCache'
import { customEntryToLesson, mergeLessons } from '../schedule/useScheduleData'
import type { CustomEntryFields } from '../schedule/useScheduleData'
import type { CustomEntry, ExamEvent, Lesson, NotificationItem, UpcomingEvent } from '../../types'
import { isoDate, parseIsoDate, tomorrowIso } from '../../ui/dateFormat'

// Если на завтра пусто (чаще всего — впереди выходные), листаем вперёд до
// ближайшего дня с уроками, а не показываем "Занятий нет" перед выходными —
// ученику интереснее увидеть расписание на понедельник. Ограничение на
// случай затяжных каникул/сбоя источника, чтобы не уйти в цикл запросов
// вникуда.
const MAX_SCHEDULE_LOOKAHEAD_DAYS = 7

/** Тянет `/api/schedule/today` + `/api/custom-entries` день за днём начиная
 * с завтра, пока не найдёт день с хотя бы одним уроком/записью, либо не
 * упрётся в лимит — тогда отдаёт последний проверенный день как есть.
 * `mergeLessons(null, [])` уже отдаёт null только когда ОБА источника
 * пусты (см. useScheduleData.ts) — на этом и держится остановка: null
 * означает "EduPage не привязан и своих записей тоже нет", а не просто
 * "уроков в этот день нет", поэтому дальше не листаем. */
async function findNextScheduleDay(): Promise<{ date: string; lessons: Lesson[] | null }> {
  const d = parseIsoDate(tomorrowIso())
  for (let i = 0; i < MAX_SCHEDULE_LOOKAHEAD_DAYS; i++) {
    const iso = isoDate(d)
    const [lessonsRes, customRes] = await Promise.all([
      getJsonCached<Lesson[]>(`/api/schedule/today?date=${iso}`),
      getJsonCached<CustomEntry[]>(`/api/custom-entries?date=${iso}`),
    ])
    const merged = mergeLessons(lessonsRes, (customRes ?? []).map(customEntryToLesson))
    if (merged === null || merged.length > 0 || i === MAX_SCHEDULE_LOOKAHEAD_DAYS - 1) {
      return { date: iso, lessons: merged }
    }
    d.setDate(d.getDate() + 1)
  }
  return { date: isoDate(d), lessons: [] } // недостижимо — цикл всегда возвращает на последней итерации
}

/** Данные Главной. me/sources/link/unlink/logout — общий useAccountShell
 * (те же настройки видны с любого экрана). Расписание на ближайший день с
 * уроками + события + сообщения — здесь: у каждого экрана свой набор
 * данных для своих карточек. */
export function useHomeData() {
  const shell = useAccountShell()
  const [scheduleDate, setScheduleDate] = useState<string>(tomorrowIso())
  const [tomorrowLessons, setTomorrowLessons] = useState<Lesson[] | null>(null)
  const [tomorrowExams, setTomorrowExams] = useState<ExamEvent[] | null>(null)
  const [events, setEvents] = useState<UpcomingEvent[] | null>(null)
  const [notifications, setNotifications] = useState<NotificationItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  // «+» на карточке расписания (см. Кабинет НИШ — Главная (ПК).dc.html) —
  // тот же /api/custom-entries, что и на Расписании, просто всегда на
  // «завтра»: карточка ровно про завтра и есть. Добавленное сразу попадает
  // прямо в саму карточку (та же проекция в Lesson, что и на Расписании) —
  // не в отдельную ленту, ученик явно просил именно так.
  const [addModalOpen, setAddModalOpen] = useState(false)
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)

  function openAddModal() {
    setAddError(null)
    setAddModalOpen(true)
  }
  function closeAddModal() {
    setAddModalOpen(false)
    setAddError(null)
  }

  async function submitCustomEntry(fields: CustomEntryFields) {
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
        entry_date: scheduleDate,
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
    setTomorrowLessons((prev) => mergeLessons(prev, [customEntryToLesson(body as CustomEntry)]))
    closeAddModal()
  }

  const reload = useCallback(async () => {
    setLoading(true)
    const [{ date, lessons }, eventsRes, notificationsRes] = await Promise.all([
      findNextScheduleDay(),
      getJsonCached<UpcomingEvent[]>('/api/events/upcoming'),
      getJsonCached<NotificationItem[]>('/api/notifications'),
    ])
    const examsRes = await getJsonCached<ExamEvent[]>(`/api/schedule/exams?from=${date}&to=${date}`)
    setScheduleDate(date)
    setTomorrowLessons(lessons)
    setTomorrowExams(examsRes)
    setEvents(eventsRes)
    setNotifications(notificationsRes)
    setLoading(false)
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  return {
    ...shell,
    scheduleDate,
    tomorrowLessons,
    tomorrowExams,
    events,
    notifications,
    loading,
    reload,
    addModalOpen,
    openAddModal,
    closeAddModal,
    submitCustomEntry,
    adding,
    addError,
  }
}

export type HomeData = ReturnType<typeof useHomeData>
