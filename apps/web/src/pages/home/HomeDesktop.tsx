import { useState } from 'react'
import { AddEntryModal } from '../schedule/parts'
import { occupiedPeriodsOf } from '../schedule/useScheduleData'
import { formatLongDate } from '../../ui/dateFormat'
import { Sidebar } from '../../ui/Sidebar'
import { SettingsDrawer } from '../../ui/SettingsDrawer'
import { EventsCard, NotificationsCard, ScheduleCard } from './parts'
import type { HomeData } from './useHomeData'

const todayLabel = formatLongDate(
  (() => {
    const d = new Date()
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
  })(),
)

export function HomeDesktop({
  data,
  onNavigate,
  onLoggedOut,
}: {
  data: HomeData
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const {
    me, scheduleDate, tomorrowLessons, tomorrowExams, events, notifications, sources, loading, link, unlink, logout,
    addModalOpen, openAddModal, closeAddModal, submitCustomEntry, adding, addError,
  } = data
  const handleLogout = async () => {
    await logout()
    onLoggedOut()
  }

  return (
    <div className="home-desktop-page">
      <Sidebar
        active="Главная"
        me={me}
        sources={sources}
        onNavigate={onNavigate}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <div className="home-main">
        <div className="home-main-inner">
          <div className="home-main-header">
            <span className="home-main-title">Главная</span>
            <span className="home-main-date">{todayLabel}</span>
          </div>

          <div className="home-main-cards">
            <ScheduleCard
              lessons={tomorrowLessons}
              exams={tomorrowExams}
              date={scheduleDate}
              loading={loading}
              onOpen={() => onNavigate('Расписание')}
              onAdd={openAddModal}
            />
            <NotificationsCard
              notifications={notifications}
              loading={loading}
              onOpen={() => onNavigate('Уведомления')}
            />
            <EventsCard events={events} loading={loading} />
          </div>
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
      />

      {addModalOpen && (
        <AddEntryModal
          dateLabel={formatLongDate(scheduleDate)}
          occupiedPeriods={occupiedPeriodsOf(tomorrowLessons)}
          submitting={adding}
          error={addError}
          onClose={closeAddModal}
          onSubmit={submitCustomEntry}
        />
      )}
    </div>
  )
}
