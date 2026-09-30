import { useCallback, useEffect, useState } from 'react'
import { useAccountShell } from '../../hooks/useAccountShell'
import { getJsonCached, invalidateCache } from '../../lib/apiCache'
import { customEntryToLesson, mergeLessons } from '../schedule/useScheduleData'
import type { CustomEntryFields } from '../schedule/useScheduleData'
import type { CustomEntry, ExamEvent, Lesson, NotificationItem, UpcomingEvent } from '../../types'
import { isoDate, parseIsoDate, todayIso, tomorrowIso } from '../../ui/dateFormat'

// Если на завтра пусто (чаще всего — впереди выходные), листаем вперёд до
// ближайшего дня с уроками, а не показываем "Занятий нет" перед выходными —
// ученику интереснее увидеть расписание на понедельник. Ограничение на
// случай затяжных каникул/сбоя источника, чтобы не уйти в цикл запросов
// вникуда.
const MAX_SCHEDULE_LOOKAHEAD_DAYS = 7

async function loadDay(iso: string): Promise<Lesson[] | null> {
  const [lessonsRes, customRes] = await Promise.all([
    getJsonCached<Lesson[]>(`/api/schedule/today?date=${iso}`),
    getJsonCached<CustomEntry[]>(`/api/custom-entries?date=${iso}`),
  ])
  return mergeLessons(lessonsRes, (customRes ?? []).map(customEntryToLesson))
}

function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(':').map(Number)
  return h * 60 + m
}

/** Сегодняшний день ещё актуален, пока не закончился последний
 * неотменённый урок. Урок без времени (своя запись без часов) — не знаем,
 * когда он кончается, поэтому такой день держим до конца суток. */
function lessonsStillAhead(lessons: Lesson[]): boolean {
  const active = lessons.filter((l) => !l.is_cancelled)
  if (active.length === 0) return false
  const times = active.map((l) => l.end ?? l.start).filter((t): t is string => !!t)
  if (times.length < active.length) return true
  const now = new Date()
  return Math.max(...times.map(toMinutes)) > now.getHours() * 60 + now.getMinutes()
}

/** Сначала сегодня — пока уроки не закончились (живая жалоба 30 сентября
 * 2026: утром Главная показывала завтрашнее расписание вместо сегодняшнего).
 * Дальше — день за днём с завтра, пока не найдётся день с хотя бы одним
 * уроком/записью, либо не упрёмся в лимит — тогда отдаём последний
 * проверенный день как есть. `mergeLessons(null, [])` отдаёт null только
 * когда ОБА источника пусты (см. useScheduleData.ts) — на этом и держится
 * остановка: null означает "EduPage не привязан и своих записей тоже нет",
 * а не просто "уроков в этот день нет", поэтому дальше не листаем. */
async function findNextScheduleDay(): Promise<{ date: string; lessons: Lesson[] | null }> {
  const today = todayIso()
  const todayLessons = await loadDay(today)
  if (todayLessons === null || lessonsStillAhead(todayLessons)) {
    return { date: today, lessons: todayLessons }
  }

  const d = parseIsoDate(tomorrowIso())
  for (let i = 0; i < MAX_SCHEDULE_LOOKAHEAD_DAYS; i++) {
    const iso = isoDate(d)
    const merged = await loadDay(iso)
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
  const [scheduleDate, setScheduleDate] = useState<string>(todayIso())
  const [tomorrowLessons, setTomorrowLessons] = useState<Lesson[] | null>(null)
  const [tomorrowExams, setTomorrowExams] = useState<ExamEvent[] | null>(null)
  const [events, setEvents] = useState<UpcomingEvent[] | null>(null)
  const [notifications, setNotifications] = useState<NotificationItem[] | null>(null)
  const [loading, setLoading] = useState(true)

  // «+» на карточке расписания (см. Кабинет НИШ — Главная (ПК).dc.html) —
  // тот же /api/custom-entries, что и на Расписании, просто на тот день,
  // который сейчас показывает карточка (scheduleDate). Добавленное сразу попадает
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
