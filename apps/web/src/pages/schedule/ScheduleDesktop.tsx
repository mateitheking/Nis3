import { useState } from 'react'
import { formatDayMonth, formatLongDate, isoDate } from '../../ui/dateFormat'
import { Sidebar } from '../../ui/Sidebar'
import { SettingsDrawer } from '../../ui/SettingsDrawer'
import {
  AddEntryModal,
  ConsultationsCard,
  DayNav,
  LessonList,
  RefreshButton,
  UpcomingCard,
  ViewToggle,
  WeekGrid,
} from './parts'
import { occupiedPeriodsOf } from './useScheduleData'
import type { ScheduleData } from './useScheduleData'

export function ScheduleDesktop({
  data,
  onNavigate,
  onLoggedOut,
}: {
  data: ScheduleData
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const {
    me, sources, view, setView, prevDay, nextDay, week, weekLessons,
    selectedDate, selectedLessons, exams, consultations, events,
    loadingWeek, loadingDay, loadingEvents, refreshing, refresh, link, unlink, logout,
    updateName, uploadAvatar, deleteAvatar,
    addModalDateIso, openAddModal, closeAddModal, submitCustomEntry, deleteCustomEntry, adding, addError,
  } = data
  const handleLogout = async () => {
    await logout()
    onLoggedOut()
  }

  // Какие номера уроков в модалке «Добавить» неактивны — зависит от того,
  // на какой день она открыта: грид открывает её на конкретный день недели
  // (week[dow]), список — на выбранный день, который может быть вне
  // текущей недели (см. useScheduleData.ts::addModalDateIso).
  const addModalOccupiedPeriods = (() => {
    if (!addModalDateIso) return []
    const dow = week.findIndex((d) => isoDate(d) === addModalDateIso)
    if (dow !== -1) return occupiedPeriodsOf(weekLessons?.[dow] ?? null)
    if (isoDate(selectedDate) === addModalDateIso) return occupiedPeriodsOf(selectedLessons)
    return []
  })()

  return (
    <div className="home-desktop-page">
      <Sidebar
        active="Расписание"
        me={me}
        sources={sources}
        onNavigate={onNavigate}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <div className="home-main">
        <div className="home-main-inner">
          <div className="home-main-header">
            <span className="home-main-title">Расписание</span>
            <div className="sch-header-actions">
              <span className="home-main-date">
                {formatDayMonth(week[0])} — {formatDayMonth(week[4])}
              </span>
              <RefreshButton refreshing={refreshing} onRefresh={refresh} />
            </div>
          </div>

          <ViewToggle view={view} onChange={setView} />

          {view === 'list' ? (
            <div className="home-card" style={{ padding: '18px 20px' }}>
              <DayNav date={selectedDate} onPrev={prevDay} onNext={nextDay} />
              <div style={{ marginTop: 16 }}>
                <LessonList
                  lessons={selectedLessons}
                  dateIso={isoDate(selectedDate)}
                  exams={exams}
                  loading={loadingDay}
                  onAdd={() => openAddModal(selectedDate)}
                  onDeleteCustom={deleteCustomEntry}
                />
              </div>
            </div>
          ) : (
            <div className="home-card" style={{ padding: 0 }}>
              <WeekGrid
                week={week}
                weekLessons={weekLessons}
                exams={exams}
                loading={loadingWeek}
                onAddDay={openAddModal}
                onDeleteCustom={deleteCustomEntry}
              />
            </div>
          )}

          <div style={{ display: 'flex', gap: 22, flexWrap: 'wrap', alignItems: 'flex-start' }}>
            <div className="home-card" style={{ flex: 1, minWidth: 320, padding: '18px 20px' }}>
              <div className="home-card-title" style={{ marginBottom: 14 }}>
                Ближайшие 30 дней
              </div>
              <UpcomingCard events={events} loading={loadingEvents} />
            </div>
            <div className="home-card" style={{ flex: 1, minWidth: 320, padding: '18px 20px' }}>
              <div className="home-card-title" style={{ marginBottom: 14 }}>
                Консультации на неделе
              </div>
              <ConsultationsCard consultations={consultations} loading={loadingWeek} />
            </div>
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
        onUpdateName={updateName}
        onUpdateAvatar={uploadAvatar}
        onDeleteAvatar={deleteAvatar}
      />

      {addModalDateIso && (
        <AddEntryModal
          dateLabel={formatLongDate(addModalDateIso)}
          occupiedPeriods={addModalOccupiedPeriods}
          submitting={adding}
          error={addError}
          onClose={closeAddModal}
          onSubmit={submitCustomEntry}
        />
      )}
    </div>
  )
}
