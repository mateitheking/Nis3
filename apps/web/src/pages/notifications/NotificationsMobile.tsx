import logo from '../../assets/nis-logo-mark.png'
import { initials } from '../../ui/dashboardParts'
import { BottomNav } from '../../ui/BottomNav'
import { NotificationsList } from './parts'
import type { NotificationsData } from './useNotificationsData'

export function NotificationsMobile({
  data,
  onNavigate,
}: {
  data: NotificationsData
  onNavigate: (key: string) => void
}) {
  const { me, items, loading, error } = data

  return (
    <div className="files-mobile-page">
      <div className="files-mobile-header">
        <div className="sch-mobile-brand">
          <img src={logo} alt="Nis3" />
          <span>Nis3.</span>
        </div>
        <div className="sch-mobile-avatar">{initials(me?.display_name ?? '??')}</div>
      </div>

      <div className="files-mobile-titleblock">
        <h1>Уведомления</h1>
        <p>Лента EduPage за последние 30 дней</p>
      </div>

      <div className="files-mobile-scroll">
        <NotificationsList items={items} loading={loading} error={error} />
      </div>

      <BottomNav active="Уведомления" onNavigate={onNavigate} />
    </div>
  )
}
