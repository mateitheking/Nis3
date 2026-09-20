import { Fragment, useState } from 'react'
import type { Consultation, ExamEvent, Lesson } from '../../types'
import { daysFromToday, formatLongDate, formatWeekdayDate, isoDate } from '../../ui/dateFormat'
import { DAY_FULL_NAMES, examBadgeFor } from './useScheduleData'
import type { CustomEntryFields } from './useScheduleData'

/** Кэш ответов на клиенте живёт час (см. lib/apiCache.ts) — эта кнопка
 * точечно обходит его на Расписании, когда только что была замена и
 * ждать час не хочется. */
export function RefreshButton({ refreshing, onRefresh }: { refreshing: boolean; onRefresh: () => void }) {
  return (
    <button
      type="button"
      className="sch-refresh-btn"
      onClick={onRefresh}
      disabled={refreshing}
      aria-label="Обновить расписание"
      title="Обновить расписание"
    >
      <svg
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        width="15"
        height="15"
        className={refreshing ? 'is-spinning' : ''}
      >
        <path d="M21 12a9 9 0 1 1-2.64-6.36" />
        <path d="M21 3v6h-6" />
      </svg>
    </button>
  )
}

export function ViewToggle({
  view,
  onChange,
}: {
  view: 'list' | 'grid'
  onChange: (v: 'list' | 'grid') => void
}) {
  return (
    <div className="sch-toggle">
      <button
        type="button"
        className={`sch-toggle-btn${view === 'list' ? ' is-active' : ''}`}
        onClick={() => onChange('list')}
      >
        Список
      </button>
      <button
        type="button"
        className={`sch-toggle-btn${view === 'grid' ? ' is-active' : ''}`}
        onClick={() => onChange('grid')}
      >
        Неделя
      </button>
    </div>
  )
}

export function DayNav({
  date,
  onPrev,
  onNext,
}: {
  date: Date
  onPrev: () => void
  onNext: () => void
}) {
  const dow = (date.getDay() + 6) % 7
  return (
    <div className="sch-daynav">
      <button type="button" className="sch-daynav-btn" onClick={onPrev} aria-label="Предыдущий день">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
          <path d="M15 18l-6-6 6-6" />
        </svg>
      </button>
      <div className="sch-daynav-label">
        <div className="sch-daynav-name">{DAY_FULL_NAMES[dow] ?? '—'}</div>
        <div className="sch-daynav-date">{formatLongDate(isoDate(date)).split(', ')[1]}</div>
      </div>
      <button type="button" className="sch-daynav-btn" onClick={onNext} aria-label="Следующий день">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>
    </div>
  )
}

/** Гость дизайна (Кабинет НИШ — Расписание.dc.html): кнопка «Добавить»
 * внизу списка дня — своя консультация/занятие, независимо от того, есть
 * ли вообще уроки в этот день (пустой день — тоже повод завести
 * репетитора/кружок). */
function AddEntryButton({ onClick }: { onClick: () => void }) {
  return (
    <button type="button" className="sch-add-row" onClick={onClick} title="Добавить свою запись">
      <svg viewBox="0 0 24 24" fill="none" stroke="#0a0a0a" strokeWidth="2.4" width="16" height="16">
        <path d="M12 5v14M5 12h14" />
      </svg>
      <span>Добавить</span>
    </button>
  )
}

export function LessonList({
  lessons,
  dateIso,
  exams,
  loading,
  onAdd,
  onDeleteCustom,
}: {
  lessons: Lesson[] | null
  dateIso: string
  exams: ExamEvent[] | null
  loading: boolean
  onAdd?: () => void
  onDeleteCustom?: (id: string) => void
}) {
  if (loading) return <div className="sch-empty">Загружаем…</div>
  return (
    <div className="sch-list">
      {!lessons ? (
        // Своя запись — не от EduPage, добавить её можно и без него (см.
        // useScheduleData.ts) — кнопка ниже не должна прятаться вместе с
        // расписанием, когда источник не привязан.
        <div className="sch-empty">EduPage не привязан или сессия истекла — зайдите в настройки</div>
      ) : lessons.length === 0 ? (
        <div className="sch-empty">Уроков нет</div>
      ) : (
        lessons.map((l, i) => {
          const exam = !l.custom ? examBadgeFor(exams, dateIso, l.subject) : null
          return (
          <div className={`sch-list-row${l.custom ? ' is-custom' : ''}`} key={i}>
            <span className="sch-list-period">{l.period ?? '?'}</span>
            <div className="sch-list-body">
              <span className={`sch-list-subject${l.is_cancelled ? ' is-cancelled' : ''}`}>{l.subject}</span>
              <div className="sch-list-teacher">
                {l.teachers[0] ?? '—'}
                {l.custom && <span className="sch-tag-custom">&nbsp;· своё</span>}
              </div>
              {l.is_cancelled && <span className="sch-tag sch-tag-cancelled">отменён</span>}
              {exam && (
                <span className="sch-tag sch-tag-exam" title={exam.title}>
                  📝 {exam.title}
                </span>
              )}
            </div>
            <div className="sch-list-meta">
              <span>{l.classrooms.join(', ')}</span>
              {l.start && l.end && (
                <span>
                  {l.start}–{l.end}
                </span>
              )}
            </div>
            {l.custom && l.id && onDeleteCustom && (
              <button
                type="button"
                className="sch-consult-delete"
                onClick={() => onDeleteCustom(l.id!)}
                aria-label="Удалить"
                title="Удалить"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            )}
          </div>
          )
        })
      )}
      {onAdd && <AddEntryButton onClick={onAdd} />}
    </div>
  )
}

/** Какой день недели подсвечивать золотым — обычно сегодня, но после
 * конца последнего урока (реального, не своей записи — своя "чилл" после
 * уроков не должна держать подсветку на сегодня весь вечер) сегодняшний
 * день уже неактуален, полезнее подсветить завтрашний (просьба
 * пользователя 16 сентября 2026: на Главной и так есть отдельная карточка
 * "Расписание на завтра" — подсветка в сетке того же смысла). Пятница
 * после уроков остаётся подсвеченной — следующий учебный день (понедельник)
 * уже вне отображаемой недели, подсвечивать нечего.
 *
 * На выходных сегодняшней даты в `week` вообще нет — сетка уже показывает
 * ближайшую предстоящую неделю, не только что прошедшую (см.
 * useScheduleData.ts::week = weekdayDates(nearestWeekday(today))) —
 * подсвечиваем её первый день, понедельник. */
function highlightedDow(week: Date[], weekLessons: (Lesson[] | null)[] | null): number {
  const todayIso = new Date().toDateString()
  const todayDow = week.findIndex((d) => d.toDateString() === todayIso)
  if (todayDow === -1) {
    const dow = new Date().getDay()
    return dow === 0 || dow === 6 ? 0 : -1
  }
  if (todayDow >= 4) return todayDow // пятница — дальше по неделе некуда
  const ends = (weekLessons?.[todayDow] ?? [])
    .filter((l) => !l.custom && l.end)
    .map((l) => l.end as string)
  if (ends.length === 0) return todayDow
  const lastEnd = ends.reduce((a, b) => (b > a ? b : a))
  const now = new Date()
  const nowHHMM = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}`
  return nowHHMM >= lastEnd ? todayDow + 1 : todayDow
}

export function WeekGrid({
  week,
  weekLessons,
  exams,
  loading,
  onAddDay,
  onDeleteCustom,
}: {
  week: Date[]
  weekLessons: (Lesson[] | null)[] | null
  exams: ExamEvent[] | null
  loading: boolean
  onAddDay?: (date: Date) => void
  onDeleteCustom?: (id: string) => void
}) {
  if (loading) return <div className="sch-empty">Загружаем…</div>
  if (!weekLessons || weekLessons.every((d) => !d)) {
    return <div className="sch-empty">EduPage не привязан или сессия истекла — зайдите в настройки</div>
  }

  // Колонка появляется по самому номеру урока — время в шапке лишь
  // подпись под ним, если оно вообще есть. Иначе своя запись без времени
  // (только "Урок 8") не получала бы колонку вовсе, хотя период у неё
  // указан явно.
  const periodSet = new Set<number>()
  const periodTimes = new Map<number, string>()
  for (const day of weekLessons) {
    for (const l of day ?? []) {
      if (l.period == null) continue
      periodSet.add(l.period)
      if (l.start && l.end && !periodTimes.has(l.period)) {
        periodTimes.set(l.period, `${l.start}–${l.end}`)
      }
    }
  }
  const periods = [...periodSet].sort((a, b) => a - b)
  if (periods.length === 0) return <div className="sch-empty">На этой неделе уроков нет</div>

  const highlightDow = highlightedDow(week, weekLessons)
  // Своя, последняя колонка — не урок, а место под «+» на добавление
  // (Кабинет НИШ — Расписание.dc.html: плавающий "+" в конце строки дня).
  // Отдельная колонка вместо overflow за пределы грида — тот уезжал бы под
  // горизонтальный скролл .sch-grid-scroll и терялся из виду.
  const columns = onAddDay ? `52px repeat(${periods.length}, minmax(56px, 1fr)) 40px` : `52px repeat(${periods.length}, minmax(56px, 1fr))`

  return (
    <div className="sch-grid-scroll">
      <div className="sch-grid" style={{ gridTemplateColumns: columns }}>
        <div className="sch-grid-corner" />
        {periods.map((p) => (
          <div className="sch-grid-headcell" key={p}>
            <span className="sch-grid-head-period">{p}</span>
            <span className="sch-grid-head-time">{periodTimes.get(p)}</span>
          </div>
        ))}
        {onAddDay && <div className="sch-grid-headcell" />}

        {week.map((date, dow) => {
          const isToday = dow === highlightDow
          const dayLessons = weekLessons[dow] ?? []
          const dateIso = isoDate(date)
          return (
            <Fragment key={dow}>
              <div className={`sch-grid-daylabel${isToday ? ' is-today' : ''}`}>
                <span>{['Пн', 'Вт', 'Ср', 'Чт', 'Пт'][dow]}</span>
              </div>
              {periods.map((p) => {
                const l = dayLessons.find((x) => x.period === p)
                const exam = l && !l.custom ? examBadgeFor(exams, dateIso, l.subject) : null
                return (
                  <div
                    className={`sch-grid-cell${isToday ? ' is-today' : ''}${l?.custom ? ' is-custom' : ''}`}
                    key={`${dow}-${p}`}
                  >
                    {l && (
                      <>
                        <span className="sch-grid-room">{l.classrooms[0] ?? ''}</span>
                        <span className={`sch-grid-subject${l.is_cancelled ? ' is-cancelled' : ''}`}>
                          {l.subject}
                        </span>
                        <span className="sch-grid-teacher">{l.teachers[0] ?? '—'}</span>
                        {l.is_cancelled && <span className="sch-tag sch-tag-cancelled sch-tag-sm">отменён</span>}
                        {exam && (
                          <span className="sch-tag sch-tag-exam sch-tag-sm" title={exam.title}>
                            📝 {exam.badge}
                          </span>
                        )}
                        {l.custom && l.id && onDeleteCustom && (
                          <button
                            type="button"
                            className="sch-grid-cell-delete"
                            onClick={() => onDeleteCustom(l.id!)}
                            aria-label="Удалить"
                            title="Удалить"
                          >
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="10" height="10">
                              <path d="M6 6l12 12M18 6L6 18" />
                            </svg>
                          </button>
                        )}
                      </>
                    )}
                  </div>
                )
              })}
              {onAddDay && (
                <div className={`sch-grid-cell sch-grid-addcell${isToday ? ' is-today' : ''}`}>
                  <button
                    type="button"
                    className="sch-grid-add-btn"
                    onClick={() => onAddDay(date)}
                    title={`Добавить на ${['понедельник', 'вторник', 'среду', 'четверг', 'пятницу'][dow]}`}
                    aria-label="Добавить свою запись"
                  >
                    <svg viewBox="0 0 24 24" fill="none" stroke="#0a0a0a" strokeWidth="2.6" width="12" height="12">
                      <path d="M12 5v14M5 12h14" />
                    </svg>
                  </button>
                </div>
              )}
            </Fragment>
          )
        })}
      </div>
    </div>
  )
}

function consultationLabel(c: Consultation): string {
  if (c.time_from && c.time_to) return `${c.time_from}–${c.time_to}`
  if (c.period_from != null) {
    return c.period_from === c.period_to ? `${c.period_from} урок` : `${c.period_from}–${c.period_to} урок`
  }
  return ''
}

export function ConsultationsCard({
  consultations,
  loading,
}: {
  consultations: (Consultation & { dow: number })[] | null
  loading: boolean
}) {
  if (loading) return <div className="sch-empty">Загружаем…</div>
  if (!consultations) return <div className="sch-empty">EduPage не привязан или сессия истекла — зайдите в настройки</div>
  if (consultations.length === 0) return <div className="sch-empty">На этой неделе консультаций нет</div>
  return (
    <div className="home-events-list" style={{ padding: 0 }}>
      {consultations.map((c, i) => (
        <div className="home-event-row" key={i}>
          <div className="sch-dot" />
          <div className="home-event-body">
            <div className="home-event-title">{c.title}</div>
            <div className="home-event-date">{['Пн', 'Вт', 'Ср', 'Чт', 'Пт'][c.dow]}</div>
          </div>
          <span className="home-event-days">{consultationLabel(c)}</span>
        </div>
      ))}
    </div>
  )
}

/** Живой баг 15 сентября 2026: нативный `<input type="time">` рисует
 * AM/PM-пикер вместо 24-часового — это решает локаль БРАУЗЕРА (не
 * `lang="ru"` на странице, как можно было бы подумать: хромиум берёт формат
 * из настроек самого браузера/ОС, а не из документа), то есть надёжно не
 * контролируется из кода приложения. Вместо борьбы с нативным пикером —
 * свой текстовый ввод, который сам расставляет двоеточие по мере ввода
 * цифр ("1730" → "17:30") и всегда 24-часовой, независимо от браузера. */
function TimeInput24({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  function handleChange(raw: string) {
    const digits = raw.replace(/\D/g, '').slice(0, 4)
    let h = digits.slice(0, 2)
    let m = digits.slice(2, 4)
    if (h.length === 2 && Number(h) > 23) h = '23'
    if (m.length === 2 && Number(m) > 59) m = '59'
    onChange(m.length > 0 ? `${h}:${m}` : h)
  }
  return (
    <input
      type="text"
      inputMode="numeric"
      className="home-settings-input"
      value={value}
      onChange={(e) => handleChange(e.target.value)}
      placeholder="17:00"
      maxLength={5}
    />
  )
}

const PERIOD_CHOICES = Array.from({ length: 13 }, (_, i) => i) // 0..12

/** Кнопки вместо ручного ввода номера урока — просьба пользователя
 * 16 сентября 2026. Занятые настоящим уроком номера неактивны (см.
 * occupiedPeriodsOf), чтобы не заводить свою запись поверх реального
 * урока по ошибке; повторный клик по уже выбранной кнопке снимает выбор
 * (номер урока необязателен). */
function PeriodPicker({
  value,
  onChange,
  occupied,
}: {
  value: string
  onChange: (v: string) => void
  occupied: number[]
}) {
  return (
    <div className="sch-period-picker">
      {PERIOD_CHOICES.map((p) => {
        const isOccupied = occupied.includes(p)
        const isSelected = value === String(p)
        return (
          <button
            key={p}
            type="button"
            className={`sch-period-btn${isSelected ? ' is-selected' : ''}`}
            disabled={isOccupied}
            onClick={() => onChange(isSelected ? '' : String(p))}
            title={isOccupied ? 'Урок уже занят' : `Урок ${p}`}
          >
            {p}
          </button>
        )
      })}
    </div>
  )
}

/** Форма «Добавить» — модалка поверх Расписания. Дизайн (Кабинет НИШ —
 * Расписание.dc.html) обозначил только точку входа (кнопка/плюсик), саму
 * форму додумываем: предмет обязателен, остальное — по желанию, как и у
 * настоящих консультаций из EduPage (тоже не всегда есть время/кабинет). */
export function AddEntryModal({
  dateLabel,
  occupiedPeriods,
  submitting,
  error,
  onClose,
  onSubmit,
}: {
  dateLabel: string
  occupiedPeriods: number[]
  submitting: boolean
  error: string | null
  onClose: () => void
  onSubmit: (fields: CustomEntryFields) => void
}) {
  const [subject, setSubject] = useState('')
  const [teacher, setTeacher] = useState('')
  const [room, setRoom] = useState('')
  const [timeFrom, setTimeFrom] = useState('')
  const [timeTo, setTimeTo] = useState('')
  const [period, setPeriod] = useState('')

  return (
    <>
      <button type="button" className="sch-modal-overlay" onClick={onClose} aria-label="Закрыть" />
      <div className="sch-modal">
        <div className="sch-modal-head">
          <span className="sch-modal-title">Добавить на {dateLabel}</span>
          <button type="button" className="sch-modal-close" onClick={onClose} aria-label="Закрыть">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>

        <div className="home-settings-field">
          <span className="home-settings-field-label">Предмет</span>
          <input
            type="text"
            className="home-settings-input"
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            placeholder="например, Репетитор по физике"
            autoFocus
          />
        </div>
        <div className="home-settings-field">
          <span className="home-settings-field-label">Номер урока (необязательно)</span>
          <PeriodPicker value={period} onChange={setPeriod} occupied={occupiedPeriods} />
        </div>
        <div className="home-settings-field">
          <span className="home-settings-field-label">Учитель (необязательно)</span>
          <input
            type="text"
            className="home-settings-input"
            value={teacher}
            onChange={(e) => setTeacher(e.target.value)}
          />
        </div>
        <div className="home-settings-field">
          <span className="home-settings-field-label">Кабинет (необязательно)</span>
          <input
            type="text"
            className="home-settings-input"
            value={room}
            onChange={(e) => setRoom(e.target.value)}
          />
        </div>
        <div className="sch-modal-time-row">
          <div className="home-settings-field">
            <span className="home-settings-field-label">Время с</span>
            <TimeInput24 value={timeFrom} onChange={setTimeFrom} />
          </div>
          <div className="home-settings-field">
            <span className="home-settings-field-label">Время до</span>
            <TimeInput24 value={timeTo} onChange={setTimeTo} />
          </div>
        </div>

        {error && <div className="home-settings-msg-error">{error}</div>}

        <button
          type="button"
          className="home-settings-linkbtn"
          disabled={submitting || !subject.trim()}
          onClick={() => onSubmit({ subject, teacher, room, timeFrom, timeTo, period })}
        >
          {submitting ? 'Добавляем…' : 'Добавить'}
        </button>
      </div>
    </>
  )
}

export function UpcomingCard({
  events,
  loading,
}: {
  events: { kind: string; badge: string; title: string; event_date: string; subject_name: string | null }[] | null
  loading: boolean
}) {
  if (loading) return <div className="sch-empty">Загружаем…</div>
  if (!events) return <div className="sch-empty">EduPage не привязан или сессия истекла — зайдите в настройки</div>
  if (events.length === 0) return <div className="sch-empty">На ближайшие 30 дней ничего не запланировано</div>
  return (
    <div className="home-events-list" style={{ padding: 0 }}>
      {events.map((e, i) => (
        <div className="home-event-row" key={i}>
          <span className="home-event-badge">{e.badge}</span>
          <div className="home-event-body">
            <div className="home-event-title">{e.title}</div>
            {e.subject_name && <div className="home-event-subject">{e.subject_name}</div>}
            <div className="home-event-date">{formatWeekdayDate(e.event_date)}</div>
          </div>
          <span className="home-event-days">{daysFromToday(e.event_date)}</span>
        </div>
      ))}
    </div>
  )
}
