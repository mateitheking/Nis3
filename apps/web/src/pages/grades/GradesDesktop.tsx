import { useState } from 'react'
import { Sidebar } from '../../ui/Sidebar'
import { SettingsDrawer } from '../../ui/SettingsDrawer'
import { QuarterTabs, RefreshBar, SubjectCard, SubjectDetail, YearNav } from './parts'
import type { GradesData } from './useGradesData'

export function GradesDesktop({
  data,
  onNavigate,
  onLoggedOut,
}: {
  data: GradesData
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const {
    me, sources, link, unlink, logout,
    quarter, setQuarter, yearLabel, prevYear, nextYear,
    subjects, note, fetchedAt, listError, loadingList, refreshing, refresh,
    selectedId, detail, loadingDetail, selectSubject,
  } = data

  const handleLogout = async () => {
    await logout()
    onLoggedOut()
  }

  return (
    <div className="home-desktop-page">
      <Sidebar
        active="Оценки"
        me={me}
        sources={sources}
        onNavigate={onNavigate}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <div className="home-main">
        <div className="home-main-inner">
          <span className="home-main-title">Оценки</span>

          <div className="gr-desktop-columns">
            <div className="gr-desktop-list-col">
              <YearNav label={yearLabel} onPrev={prevYear} onNext={nextYear} />
              <QuarterTabs quarter={quarter} onChange={setQuarter} />
              <RefreshBar fetchedAt={fetchedAt} refreshing={refreshing} onRefresh={refresh} />

              {loadingList ? (
                <div className="gr-skeleton-list">
                  <div className="gr-skeleton" />
                  <div className="gr-skeleton" />
                  <div className="gr-skeleton" />
                </div>
              ) : listError ? (
                <div className="gr-desktop-empty">СУШ не привязан или сессия истекла</div>
              ) : note ? (
                <div className="gr-desktop-empty">{note}</div>
              ) : subjects && subjects.length > 0 ? (
                <div className="gr-mobile-grid">
                  {subjects.map((s) => (
                    <SubjectCard
                      key={s.name}
                      subject={s}
                      active={s.name === selectedId}
                      onClick={() => selectSubject(s.name)}
                    />
                  ))}
                </div>
              ) : (
                <div className="gr-desktop-empty">Предметов не найдено</div>
              )}
            </div>

            <div className="gr-desktop-detail-col">
              {!selectedId ? (
                <div className="gr-desktop-empty">Выберите предмет слева</div>
              ) : (
                <SubjectDetail
                  key={selectedId}
                  subject={detail ?? subjects?.find((s) => s.name === selectedId) ?? null}
                  loading={loadingDetail}
                />
              )}
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
      />
    </div>
  )
}
