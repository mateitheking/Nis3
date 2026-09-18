import type { ExamEvent, Lesson, NotificationItem, UpcomingEvent } from '../../types'
import {
  daysFromToday,
  daysOffsetFromToday,
  formatMessageDateTime,
  formatShortDayMonth,
  formatWeekdayDate,
  hoursUntil,
  tomorrowIso,
  weekdayAccusative,
} from '../../ui/dateFormat'
import { examBadgeFor } from '../schedule/useScheduleData'

function subjectShort(subject: string): string {
  return subject.split(' ')[0]
}

export function ScheduleCard({
  lessons,
  exams,
  date,
  loading,
  onOpen,
  onAdd,
}: {
  lessons: Lesson[] | null
  exams: ExamEvent[] | null
  /** Реальный день, который показывает карточка — не всегда буквально
   * завтра: если на завтра пусто (выходные), это ближайший день с уроками
   * (см. useHomeData::findNextScheduleDay). */
  date: string
  loading: boolean
  onOpen?: () => void
  onAdd?: () => void
}) {
  const title =
    date === tomorrowIso()
      ? `Расписание на завтра, ${formatShortDayMonth(date)}`
      : `Расписание на ${weekdayAccusative(date)}, ${formatShortDayMonth(date)}`
  const first = lessons && lessons.length > 0 ? lessons[0] : null
  const hoursToFirst = first?.start ? hoursUntil(first.start, daysOffsetFromToday(date)) : null

  const Wrap = onOpen ? 'button' : 'div'

  return (
    <div className="home-schedule-wrap">
      <Wrap
        className="home-card home-schedule-card"
        onClick={onOpen}
        type={onOpen ? 'button' : undefined}
      >
        <div className="home-schedule-head">
          {hoursToFirst !== null && (
            <div className="home-schedule-head-row">
              <span className="home-schedule-hint">До первого урока</span>
              <span className="home-schedule-countdown">через {hoursToFirst} ч</span>
            </div>
          )}
          <div className="home-schedule-title">{title}</div>
        </div>
        {loading ? (
          <div className="home-schedule-empty">Загружаем…</div>
        ) : !lessons ? (
          <div className="home-schedule-empty">
            EduPage не привязан или сессия истекла — зайдите в настройки
          </div>
        ) : lessons.length === 0 ? (
          <div className="home-schedule-empty">Занятий нет</div>
        ) : (
          <div className="home-schedule-grid" style={{ gridTemplateColumns: `repeat(${lessons.length}, 1fr)` }}>
            {lessons.map((l, i) => {
              const exam = !l.custom ? examBadgeFor(exams, date, l.subject) : null
              return (
                <div className="home-schedule-cell" key={i}>
                  {exam && (
                    <span className="home-schedule-exam-dot" title={exam.title}>
                      📝
                    </span>
                  )}
                  <span className="home-schedule-period">{l.period ?? '?'}</span>
                  <span className="home-schedule-subject">{subjectShort(l.subject)}</span>
                  <span className="home-schedule-room">{l.classrooms[0] ?? ''}</span>
                  <span className="home-schedule-time">{l.start}</span>
                  <span className="home-schedule-time">{l.end}</span>
                </div>
              )
            })}
          </div>
        )}
      </Wrap>
      {onAdd && (
        <button
          type="button"
          className="home-schedule-add"
          onClick={onAdd}
          title="Добавить консультацию"
          aria-label="Добавить консультацию"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="#0a0a0a" strokeWidth="2.4" width="20" height="20">
            <path d="M12 5v14M5 12h14" />
          </svg>
        </button>
      )}
    </div>
  )
}

const HOME_NOTIFICATIONS_PREVIEW = 4

export function NotificationsCard({
  notifications,
  loading,
  onOpen,
}: {
  notifications: NotificationItem[] | null
  loading: boolean
  onOpen?: () => void
}) {
  const Wrap = onOpen ? 'button' : 'div'
  const preview = notifications?.slice(0, HOME_NOTIFICATIONS_PREVIEW) ?? null

  return (
    <Wrap
      className="home-card home-messages-card home-notifications-card"
      onClick={onOpen}
      type={onOpen ? 'button' : undefined}
    >
      <div className="home-card-head">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="home-card-icon">
          <path d="M3 6h18v12H3z" />
          <path d="M3 6l9 7 9-7" />
        </svg>
        <span className="home-card-title">Уведомления</span>
        {notifications && notifications.length > HOME_NOTIFICATIONS_PREVIEW && (
          <span className="home-card-more">Все →</span>
        )}
      </div>
      {loading ? (
        <div className="home-schedule-empty">Загружаем…</div>
      ) : !preview ? (
        <div className="home-schedule-empty">
          EduPage не привязан или сессия истекла — зайдите в настройки
        </div>
      ) : preview.length === 0 ? (
        <div className="home-schedule-empty">За последние 30 дней уведомлений нет</div>
      ) : (
        <div className="home-events-list">
          {preview.map((n) => (
            <div className="home-event-row" key={n.id}>
              <span className="home-event-badge">{n.badge}</span>
              <div className="home-event-body">
                <div className="home-event-title">{n.title}</div>
                <div className="home-event-date">
                  {n.kind === 'message' && n.author ? n.author : n.event_date ? formatWeekdayDate(n.event_date) : ''}
                </div>
              </div>
              <span className="home-event-days">{formatMessageDateTime(n.posted_at)}</span>
            </div>
          ))}
        </div>
      )}
    </Wrap>
  )
}

export function EventsCard({ events, loading }: { events: UpcomingEvent[] | null; loading: boolean }) {
  return (
    <div className="home-card">
      <div className="home-card-head">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" className="home-card-icon">
          <rect x="3" y="4" width="18" height="17" rx="2" />
          <path d="M3 9h18M8 2v4M16 2v4" />
        </svg>
        <span className="home-card-title">Ближайшие события</span>
      </div>
      {loading ? (
        <div className="home-schedule-empty">Загружаем…</div>
      ) : !events ? (
        <div className="home-schedule-empty">
          EduPage не привязан или сессия истекла — зайдите в настройки
        </div>
      ) : events.length === 0 ? (
        <div className="home-schedule-empty">На ближайшие 30 дней ничего не запланировано</div>
      ) : (
        <div className="home-events-list">
          {events.map((e, i) => (
            <div className="home-event-row" key={i}>
              <span className="home-event-badge">{e.badge}</span>
              <div className="home-event-body">
                <div className="home-event-title">{e.title}</div>
                <div className="home-event-date">{formatWeekdayDate(e.event_date)}</div>
              </div>
              <span className="home-event-days">{daysFromToday(e.event_date)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
