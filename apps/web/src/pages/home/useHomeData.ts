import { useCallback, useEffect, useState } from 'react'
import { useAccountShell } from '../../hooks/useAccountShell'
import { getJsonCached, invalidateCache } from '../../lib/apiCache'
import { customEntryToLesson, mergeLessons } from '../schedule/useScheduleData'
import type { CustomEntryFields } from '../schedule/useScheduleData'
import type { CustomEntry, ExamEvent, Lesson, NotificationItem, UpcomingEvent } from '../../types'
import { tomorrowIso } from '../../ui/dateFormat'

/** Данные Главной. me/sources/link/unlink/logout — общий useAccountShell
 * (те же настройки видны с любого экрана). Расписание на завтра + события
 * + сообщения — здесь: у каждого экрана свой набор данных для своих
 * карточек. */
export function useHomeData() {
  const shell = useAccountShell()
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
        entry_date: tomorrowIso(),
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
    const [lessonsRes, customRes, examsRes, eventsRes, notificationsRes] = await Promise.all([
      getJsonCached<Lesson[]>(`/api/schedule/today?date=${tomorrowIso()}`),
      getJsonCached<CustomEntry[]>(`/api/custom-entries?date=${tomorrowIso()}`),
      getJsonCached<ExamEvent[]>(`/api/schedule/exams?from=${tomorrowIso()}&to=${tomorrowIso()}`),
      getJsonCached<UpcomingEvent[]>('/api/events/upcoming'),
      getJsonCached<NotificationItem[]>('/api/notifications'),
    ])
    setTomorrowLessons(mergeLessons(lessonsRes, (customRes ?? []).map(customEntryToLesson)))
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
