import type { ChangeEvent, ReactNode } from 'react'

interface FieldProps {
  label: string
  type: 'text' | 'email' | 'password'
  value: string
  onChange: (value: string) => void
  placeholder: string
  mobile?: boolean
  invalid?: boolean
  hint?: string
  autoComplete?: string
}

export function Field({
  label,
  type,
  value,
  onChange,
  placeholder,
  mobile,
  invalid,
  hint,
  autoComplete,
}: FieldProps) {
  return (
    <div className="af-field">
      <label className="af-label">{label}</label>
      <input
        type={type}
        value={value}
        onChange={(e: ChangeEvent<HTMLInputElement>) => onChange(e.target.value)}
        placeholder={placeholder}
        autoComplete={autoComplete}
        className={`af-input${mobile ? ' af-input--mobile' : ''}${invalid ? ' is-invalid' : ''}`}
      />
      {hint && <span className="af-hint">{hint}</span>}
    </div>
  )
}

export function Checkbox({
  checked,
  onToggle,
  label,
  mobile,
  labelFontSize,
}: {
  checked: boolean
  onToggle: () => void
  label: string
  mobile?: boolean
  /** Точный размер подписи чекбокса отличается по экрану в дизайне
   * (Регистрация: 13/13.5px, Вход: 13.5/14px) — не подгоняем под одно
   * значение, переопределяем точечно, где дизайн реально другой. */
  labelFontSize?: number
}) {
  return (
    <button type="button" onClick={onToggle} className="af-checkbox-row">
      <span
        className={`af-checkbox-box${mobile ? ' af-checkbox-box--mobile' : ''}${checked ? ' is-checked' : ''}`}
      >
        {checked ? '✓' : ''}
      </span>
      <span
        className={`af-checkbox-label${mobile ? ' af-checkbox-label--mobile' : ''}`}
        style={labelFontSize ? { fontSize: labelFontSize } : undefined}
      >
        {label}
      </span>
    </button>
  )
}

export function PrimaryButton({
  label,
  connecting,
  disabled,
  onClick,
  mobile,
}: {
  label: string
  connecting: boolean
  disabled?: boolean
  onClick: () => void
  mobile?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={`af-btn af-btn-primary${mobile ? ' af-btn--mobile' : ''}`}
    >
      {connecting && <span className="af-spinner" />}
      {label}
    </button>
  )
}

export function Divider() {
  return (
    <div className="af-divider">
      <div className="af-divider-line" />
      <span className="af-divider-text">или</span>
      <div className="af-divider-line" />
    </div>
  )
}

export function SecondaryButton({
  label,
  mobile,
  onClick,
}: {
  label: string
  mobile?: boolean
  onClick?: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`af-btn af-btn-secondary${mobile ? ' af-btn--mobile' : ''}`}
    >
      {label}
    </button>
  )
}

export function HelpRow({ mobile }: { mobile?: boolean }) {
  return (
    <div className="af-help-row">
      <span className={`af-help-text${mobile ? ' af-help-text--mobile' : ''}`}>
        Нужна помощь?
      </span>
      <a
        href="https://t.me"
        target="_blank"
        rel="noreferrer"
        className={`af-help-link${mobile ? ' af-help-link--mobile' : ''}`}
      >
        <svg viewBox="0 0 24 24" fill="currentColor" className="af-help-icon">
          <path d="M22.05 3.44L2.8 11.02c-1.28.51-1.27 1.22-.23 1.55l4.92 1.54 1.9 6.02c.23.63.12.88.79.88.51 0 .74-.24 1.02-.51l2.44-2.36 5.05 3.72c.93.52 1.6.25 1.83-.86l3.32-15.64c.34-1.36-.24-1.95-1.79-1.42zM8.98 13.6l10.05-6.35c.5-.3.96-.14.58.19L11.2 14.6c-.34.29-.68.45-1.32.48z" />
        </svg>
        Telegram
      </a>
    </div>
  )
}

export function ErrorBanner({ children }: { children: ReactNode }) {
  return <div className="af-error-banner">{children}</div>
}

export function SuccessPanel({
  message,
  onContinue,
}: {
  message: string
  onContinue: () => void
}) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      <div className="af-success-row">
        <span className="af-success-dot">✓</span>
        <span className="af-success-label">{message}</span>
      </div>
      <button type="button" onClick={onContinue} className="af-btn af-btn-primary">
        Перейти в кабинет
      </button>
    </div>
  )
}
