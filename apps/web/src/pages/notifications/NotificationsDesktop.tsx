import { useState } from 'react'
import { Sidebar } from '../../ui/Sidebar'
import { SettingsDrawer } from '../../ui/SettingsDrawer'
import { NotificationsList } from './parts'
import type { NotificationsData } from './useNotificationsData'

export function NotificationsDesktop({
  data,
  onNavigate,
  onLoggedOut,
}: {
  data: NotificationsData
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { me, sources, items, loading, error, link, unlink, logout, updateName, uploadAvatar, deleteAvatar, changePassword, resendVerification } = data
  const handleLogout = async () => {
    await logout()
    onLoggedOut()
  }

  return (
    <div className="home-desktop-page">
      <Sidebar
        active="Уведомления"
        me={me}
        sources={sources}
        onNavigate={onNavigate}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <div className="home-main">
        <div className="home-main-inner">
          <div className="home-main-header">
            <span className="home-main-title">Уведомления</span>
            <span className="home-main-date">Лента EduPage за последние 30 дней</span>
          </div>

          <NotificationsList items={items} loading={loading} error={error} />
        </div>
      </div>

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        variant="desktop"
        me={me}
        sources={sources}
        onUnlink={unlink}
        onLink={link}
        onLogout={handleLogout}
        onUpdateName={updateName}
        onUpdateAvatar={uploadAvatar}
        onDeleteAvatar={deleteAvatar}
        onChangePassword={changePassword}
        onResendVerification={resendVerification}
      />
    </div>
  )
}
