import logo from '../../assets/nis-logo-mark.png'
import { initials } from '../../ui/dashboardParts'
import { BottomNav } from '../../ui/BottomNav'
import { formatDayMonth, isoDate } from '../../ui/dateFormat'
import { ConsultationsCard, DayNav, LessonList, RefreshButton, UpcomingCard, ViewToggle, WeekGrid } from './parts'
import type { ScheduleData } from './useScheduleData'

export function ScheduleMobile({
  data,
  onNavigate,
}: {
  data: ScheduleData
  onNavigate: (key: string) => void
}) {
  const {
    me, view, setView, prevDay, nextDay, week, weekLessons,
    selectedDate, selectedLessons, exams, consultations, events,
    loadingWeek, loadingDay, loadingEvents, refreshing, refresh, deleteCustomEntry,
  } = data

  return (
    <div className="sch-mobile-page">
      <div className="sch-mobile-topbar">
        <div className="sch-mobile-topbar-left">
          <button
            type="button"
            className="sch-mobile-back"
            onClick={() => onNavigate('Главная')}
            aria-label="Назад"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
              <path d="M15 18l-6-6 6-6" />
            </svg>
          </button>
          <div className="sch-mobile-brand">
            <img src={logo} alt="Nis3" />
            <span>Nis3.</span>
          </div>
        </div>
        <div className="sch-mobile-avatar">{initials(me?.display_name ?? '??')}</div>
      </div>

      <div className="sch-mobile-titleblock">
        <h1>Расписание</h1>
        <div className="sch-header-actions">
          <p>
            {formatDayMonth(week[0])} — {formatDayMonth(week[4])}
          </p>
          <RefreshButton refreshing={refreshing} onRefresh={refresh} />
        </div>
        <div className="sch-mobile-toggle-wrap">
          <ViewToggle view={view} onChange={setView} />
        </div>
      </div>

      <div className="sch-mobile-scroll">
        {view === 'list' ? (
          <div className="sch-section">
            <DayNav date={selectedDate} onPrev={prevDay} onNext={nextDay} />
            <LessonList
              lessons={selectedLessons}
              dateIso={isoDate(selectedDate)}
              exams={exams}
              loading={loadingDay}
              onDeleteCustom={deleteCustomEntry}
            />
          </div>
        ) : (
          <WeekGrid
            week={week}
            weekLessons={weekLessons}
            exams={exams}
            loading={loadingWeek}
            onDeleteCustom={deleteCustomEntry}
          />
        )}

        <div className="sch-section">
          <span className="sch-section-label">Консультации на неделе</span>
          <ConsultationsCard consultations={consultations} loading={loadingWeek} />
        </div>

        <div className="sch-section">
          <span className="sch-section-label">Ближайшие 30 дней</span>
          <UpcomingCard events={events} loading={loadingEvents} />
        </div>
      </div>

      <BottomNav active="Расписание" onNavigate={onNavigate} />
    </div>
  )
}
