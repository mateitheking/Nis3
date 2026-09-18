import logo from '../../assets/nis-logo-mark.png'
import { initials } from '../../ui/dashboardParts'
import { BottomNav } from '../../ui/BottomNav'
import { QuarterTabs, RefreshBar, SubjectCard, SubjectDetail, YearNav } from './parts'
import type { GradesData } from './useGradesData'

export function GradesMobile({
  data,
  onNavigate,
}: {
  data: GradesData
  onNavigate: (key: string) => void
}) {
  const {
    me,
    quarter, setQuarter, yearLabel, prevYear, nextYear,
    subjects, note, fetchedAt, listError, loadingList, refreshing, refresh,
    selectedId, detail, loadingDetail, selectSubject, closeDetail,
  } = data

  const selectedSubject = subjects?.find((s) => s.name === selectedId) ?? null

  return (
    <div className="gr-mobile-page">
      <div className="gr-mobile-header">
        <div className="gr-mobile-brand">
          <img src={logo} alt="Nis3" />
          <span>Nis3.</span>
        </div>
        <div className="sch-mobile-avatar">{initials(me?.display_name ?? '??')}</div>
      </div>

      {!selectedId ? (
        <>
          <div className="gr-mobile-titleblock">
            <h1>Оценки</h1>
            <QuarterTabs quarter={quarter} onChange={setQuarter} />
            <YearNav label={yearLabel} onPrev={prevYear} onNext={nextYear} />
            <RefreshBar fetchedAt={fetchedAt} refreshing={refreshing} onRefresh={refresh} />
          </div>

          <div className="gr-mobile-scroll">
            {loadingList ? (
              <div className="gr-skeleton-list">
                <div className="gr-skeleton" />
                <div className="gr-skeleton" />
                <div className="gr-skeleton" />
              </div>
            ) : listError ? (
              <div className="gr-desktop-empty">{listError}</div>
            ) : note ? (
              <div className="gr-desktop-empty">{note}</div>
            ) : subjects && subjects.length > 0 ? (
              <div className="gr-mobile-grid">
                {subjects.map((s) => (
                  <SubjectCard
                    key={s.name}
                    subject={s}
                    active={false}
                    onClick={() => selectSubject(s.name)}
                  />
                ))}
              </div>
            ) : (
              <div className="gr-desktop-empty">Предметов не найдено</div>
            )}
          </div>
        </>
      ) : (
        <div className="gr-mobile-scroll">
          <div className="gr-mobile-detail-head">
            <button type="button" className="gr-mobile-back" onClick={closeDetail} aria-label="Назад">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="16" height="16">
                <path d="M15 18l-6-6 6-6" />
              </svg>
            </button>
            <div className="gr-mobile-detail-name">{selectedSubject?.name}</div>
          </div>
          <SubjectDetail
            key={selectedId}
            subject={detail ?? selectedSubject ?? null}
            loading={loadingDetail}
          />
        </div>
      )}

      <BottomNav active="Оценки" onNavigate={onNavigate} />
    </div>
  )
}
