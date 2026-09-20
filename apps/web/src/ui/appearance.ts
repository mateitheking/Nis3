import { useCallback, useEffect, useState } from 'react'

export type ThemeMode = 'system' | 'light' | 'dark'
export type AccentKey = 'gold' | 'blue' | 'green' | 'purple' | 'rose'

const THEME_KEY = 'nis-theme'
const ACCENT_KEY = 'nis-accent'

export const ACCENTS: { key: AccentKey; label: string; swatch: string }[] = [
  { key: 'gold', label: 'Золотой', swatch: '#d4af5a' },
  { key: 'blue', label: 'Синий', swatch: '#5b8def' },
  { key: 'green', label: 'Зелёный', swatch: '#4caf6a' },
  { key: 'purple', label: 'Фиолетовый', swatch: '#9b7fd4' },
  { key: 'rose', label: 'Розовый', swatch: '#d97fa0' },
]

export function getStoredTheme(): ThemeMode {
  const v = localStorage.getItem(THEME_KEY)
  return v === 'light' || v === 'dark' || v === 'system' ? v : 'system'
}

export function getStoredAccent(): AccentKey {
  const v = localStorage.getItem(ACCENT_KEY)
  return ACCENTS.some((a) => a.key === v) ? (v as AccentKey) : 'gold'
}

function resolveTheme(mode: ThemeMode): 'light' | 'dark' {
  if (mode === 'system') {
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  }
  return mode
}

export function applyAppearance(theme: ThemeMode, accent: AccentKey) {
  document.documentElement.dataset.theme = resolveTheme(theme)
  document.documentElement.dataset.accent = accent
}

/** Тема и акцент живут в localStorage + атрибутах <html> (см. index.html —
 * там же читаются синхронно до первой отрисовки, чтобы не было вспышки
 * неправильной темы). Хук нужен только настройкам — для подсветки текущего
 * выбора; само приложение ничего не перерисовывает, CSS реагирует сам. */
export function useAppearance() {
  const [theme, setThemeState] = useState<ThemeMode>(getStoredTheme)
  const [accent, setAccentState] = useState<AccentKey>(getStoredAccent)

  useEffect(() => {
    applyAppearance(theme, accent)
  }, [theme, accent])

  useEffect(() => {
    if (theme !== 'system') return
    const mq = window.matchMedia('(prefers-color-scheme: light)')
    const onChange = () => applyAppearance('system', accent)
    mq.addEventListener('change', onChange)
    return () => mq.removeEventListener('change', onChange)
  }, [theme, accent])

  const setTheme = useCallback((v: ThemeMode) => {
    localStorage.setItem(THEME_KEY, v)
    setThemeState(v)
  }, [])
  const setAccent = useCallback((v: AccentKey) => {
    localStorage.setItem(ACCENT_KEY, v)
    setAccentState(v)
  }, [])

  return { theme, accent, setTheme, setAccent }
}
