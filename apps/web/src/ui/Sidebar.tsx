import logo from '../assets/nis-logo-mark.png'
import type { Me, SourcesStatus } from '../types'
import { Avatar, StatusDot } from './dashboardParts'
import { NAV_ITEMS, type NavKey } from './navIcons'

export function Sidebar({
  active,
  me,
  sources,
  onNavigate,
  onOpenSettings,
}: {
  active: NavKey
  me: Me | null
  sources: SourcesStatus | null
  onNavigate: (key: string) => void
  onOpenSettings: () => void
}) {
  return (
    <div className="home-sidebar">
      <div className="home-sidebar-brand">
        <img src={logo} alt="Nis3" className="home-sidebar-logo" />
        <span>Nis3.</span>
      </div>

      <div className="home-sidebar-profile">
        <Avatar name={me?.display_name ?? '??'} size={38} avatarUrl={me?.avatar_url} />
        <div className="home-sidebar-profile-text">
          <div className="home-sidebar-profile-name">{me?.display_name ?? '…'}</div>
          <div className="home-sidebar-profile-sub">Ученик</div>
        </div>
        <button type="button" className="home-sidebar-gear" onClick={onOpenSettings} aria-label="Настройки">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="14" height="14">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 11-4 0v-.09a1.65 1.65 0 00-1-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 110-4h.09a1.65 1.65 0 001.51-1 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33h0a1.65 1.65 0 001-1.51V3a2 2 0 114 0v.09a1.65 1.65 0 001 1.51h0a1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82v0a1.65 1.65 0 001.51 1H21a2 2 0 110 4h-.09a1.65 1.65 0 00-1.51 1z" />
          </svg>
        </button>
      </div>

      <div className="home-sidebar-nav">
        {NAV_ITEMS.map((item) => (
          <button
            key={item.key}
            type="button"
            className={`home-sidebar-nav-item${item.key === active ? ' is-active' : ''}`}
            onClick={() => item.key !== active && onNavigate(item.key)}
          >
            {item.icon}
            <span>{item.key}</span>
          </button>
        ))}
        <button
          type="button"
          className={`home-sidebar-nav-item${active === 'NisAI' ? ' is-active' : ''}`}
          onClick={() => active !== 'NisAI' && onNavigate('NisAI')}
        >
          <span className="home-sidebar-ai-icon">
            <span>AI</span>
          </span>
          <span>NisAI</span>
        </button>
      </div>

      <a
        href="https://t.me/+pQRfzea3tM8zM2Zi"
        target="_blank"
        rel="noreferrer"
        className="home-sidebar-telegram"
      >
        <svg viewBox="0 0 24 24" fill="currentColor" className="home-sidebar-telegram-icon">
          <path d="M22.05 3.44L2.8 11.02c-1.28.51-1.27 1.22-.23 1.55l4.92 1.54 1.9 6.02c.23.63.12.88.79.88.51 0 .74-.24 1.02-.51l2.44-2.36 5.05 3.72c.93.52 1.6.25 1.83-.86l3.32-15.64c.34-1.36-.24-1.95-1.79-1.42zM8.98 13.6l10.05-6.35c.5-.3.96-.14.58.19L11.2 14.6c-.34.29-.68.45-1.32.48z" />
        </svg>
        <span>Telegram</span>
      </a>

      <div className="home-sidebar-status">
        <StatusDot label="СУШ" status={sources?.sush} />
        <StatusDot label="EduPage" status={sources?.edupage} />
      </div>
    </div>
  )
}
