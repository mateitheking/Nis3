import type { ReactElement } from 'react'

export const NavIcon = {
  home: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="19" height="19">
      <path d="M4 11l8-7 8 7" />
      <path d="M6 10v10h12V10" />
    </svg>
  ),
  schedule: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="19" height="19">
      <rect x="3" y="4" width="18" height="17" rx="2" />
      <path d="M3 9h18M8 2v4M16 2v4" />
    </svg>
  ),
  grades: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="19" height="19">
      <path d="M4 20V10M12 20V4M20 20v-7" />
    </svg>
  ),
  files: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="19" height="19">
      <path d="M6 2h9l5 5v13a2 2 0 01-2 2H6a2 2 0 01-2-2V4a2 2 0 012-2z" />
      <path d="M15 2v5h5" />
    </svg>
  ),
  notifications: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" width="19" height="19">
      <path d="M18 8a6 6 0 00-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M13.73 21a2 2 0 01-3.46 0" />
    </svg>
  ),
}

export type NavKey = 'Главная' | 'Расписание' | 'Оценки' | 'Файлы' | 'Уведомления' | 'NisAI'

export const NAV_ITEMS: { key: NavKey; icon: ReactElement }[] = [
  { key: 'Главная', icon: NavIcon.home },
  { key: 'Расписание', icon: NavIcon.schedule },
  { key: 'Оценки', icon: NavIcon.grades },
  { key: 'Файлы', icon: NavIcon.files },
  { key: 'Уведомления', icon: NavIcon.notifications },
]
