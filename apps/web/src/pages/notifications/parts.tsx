import type { NotificationItem } from '../../types'
import { formatWeekdayDate } from '../../ui/dateFormat'

/** 'YYYY-MM-DDTHH:MM:SS' (см. apps/api/main.py::notifications, datetime.isoformat()
 * без таймзоны) -> дата и время без создания Date — сервер и ученик в одном
 * поясе, лишнее преобразование через new Date() тут не нужно. */
function dayPart(iso: string): string {
  return iso.slice(0, 10)
}
function timePart(iso: string): string {
  return iso.slice(11, 16)
}

export function NotificationsList({
  items,
  loading,
  error,
}: {
  items: NotificationItem[] | null
  loading: boolean
  error: string | null
}) {
  if (loading) return <div className="home-schedule-empty">Загружаем…</div>
  if (error || !items) {
    return (
      <div className="home-schedule-empty">
        EduPage не привязан или сессия истекла — зайдите в настройки
      </div>
    )
  }
  if (items.length === 0) {
    return <div className="home-schedule-empty">За последние 30 дней уведомлений нет</div>
  }

  const groups: { day: string; items: NotificationItem[] }[] = []
  for (const n of items) {
    const key = dayPart(n.posted_at)
    const last = groups[groups.length - 1]
    if (last && last.day === key) last.items.push(n)
    else groups.push({ day: key, items: [n] })
  }

  return (
    <div className="notif-groups">
      {groups.map((g) => (
        <div className="notif-group" key={g.day}>
          <div className="notif-group-date">{formatWeekdayDate(g.day)}</div>
          <div className="notif-group-list">
            {g.items.map((n) => (
              <div className="notif-row" key={n.id}>
                <span className={`notif-badge notif-badge-${n.kind}`}>{n.badge}</span>
                <div className="notif-body">
                  <div className="notif-title">{n.title}</div>
                  {n.kind === 'message' && n.author ? (
                    <div className="notif-sub">{n.author}</div>
                  ) : n.event_date ? (
                    <div className="notif-sub">Предстоит: {formatWeekdayDate(n.event_date)}</div>
                  ) : null}
                </div>
                <span className="notif-time">{timePart(n.posted_at)}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}
