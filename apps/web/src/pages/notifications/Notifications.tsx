import { useMediaQuery } from '../../hooks/useMediaQuery'
import { NotificationsDesktop } from './NotificationsDesktop'
import { NotificationsMobile } from './NotificationsMobile'
import { useNotificationsData } from './useNotificationsData'

export function Notifications({
  onNavigate,
  onLoggedOut,
}: {
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const isDesktop = useMediaQuery('(min-width: 900px)')
  const data = useNotificationsData()

  return isDesktop ? (
    <NotificationsDesktop data={data} onNavigate={onNavigate} onLoggedOut={onLoggedOut} />
  ) : (
    <NotificationsMobile data={data} onNavigate={onNavigate} />
  )
}
