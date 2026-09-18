import { useState } from 'react'
import { Avatar, StatusDot } from '../../ui/dashboardParts'
import { BottomNav } from '../../ui/BottomNav'
import { SettingsDrawer } from '../../ui/SettingsDrawer'
import { EventsCard, NotificationsCard, ScheduleCard } from './parts'
import type { HomeData } from './useHomeData'

export function HomeMobile({
  data,
  onNavigate,
  onLoggedOut,
}: {
  data: HomeData
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const { me, scheduleDate, tomorrowLessons, tomorrowExams, events, notifications, sources, loading, link, unlink, logout } = data
  const handleLogout = async () => {
    await logout()
    onLoggedOut()
  }

  return (
    <div className="home-mobile-page">
      <div className="home-mobile-header">
        <button
          type="button"
          className="home-mobile-menu-btn"
          onClick={() => setSettingsOpen(true)}
          aria-label="Настройки"
        >
          <span className="home-mobile-menu-bar" />
          <span className="home-mobile-menu-bar" />
          <span className="home-mobile-menu-bar" />
        </button>
        <Avatar name={me?.display_name ?? '??'} size={44} />
        <span className="home-mobile-name">{me?.display_name ?? '…'}</span>
        <span className="home-mobile-sub">Ученик Nis3</span>
      </div>

      <div className="home-mobile-scroll">
        <ScheduleCard
          lessons={tomorrowLessons}
          exams={tomorrowExams}
          date={scheduleDate}
          loading={loading}
          onOpen={() => onNavigate('Расписание')}
        />
        <NotificationsCard
          notifications={notifications}
          loading={loading}
          onOpen={() => onNavigate('Уведомления')}
        />
        <EventsCard events={events} loading={loading} />
        <div className="home-mobile-status-row">
          <StatusDot label="СУШ" status={sources?.sush} />
          <StatusDot label="EduPage" status={sources?.edupage} />
        </div>
      </div>

      <BottomNav active="Главная" onNavigate={onNavigate} />

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        variant="mobile"
        me={me}
        sources={sources}
        onUnlink={unlink}
        onLink={link}
        onLogout={handleLogout}
      />
    </div>
  )
}
