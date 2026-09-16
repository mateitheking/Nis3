import type { LinkFields, LinkResult } from '../hooks/useAccountShell'
import type { Me, SourcesStatus } from '../types'
import { SettingsPanelBody } from './dashboardParts'

export function SettingsDrawer({
  open,
  onClose,
  variant,
  me,
  sources,
  onUnlink,
  onLink,
  onLogout,
}: {
  open: boolean
  onClose: () => void
  variant: 'mobile' | 'desktop'
  me: Me | null
  sources: SourcesStatus | null
  onUnlink: (source: 'sush' | 'edupage') => void
  onLink: (source: 'sush' | 'edupage', fields: LinkFields) => Promise<LinkResult>
  onLogout: () => void
}) {
  if (!open) return null
  return (
    <>
      <button
        type="button"
        className="home-settings-overlay"
        onClick={onClose}
        aria-label="Закрыть настройки"
      />
      <div
        className={variant === 'mobile' ? 'home-mobile-settings-panel' : 'home-desktop-settings-panel'}
      >
        <div className="home-settings-panel-head">
          <span className="home-settings-panel-title">Настройки</span>
          <button type="button" className="home-settings-close" onClick={onClose} aria-label="Закрыть">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="13" height="13">
              <path d="M6 6l12 12M18 6L6 18" />
            </svg>
          </button>
        </div>
        <div className="home-settings-panel-scroll">
          <SettingsPanelBody me={me} sources={sources} onUnlink={onUnlink} onLink={onLink} onLogout={onLogout} />
        </div>
      </div>
    </>
  )
}
