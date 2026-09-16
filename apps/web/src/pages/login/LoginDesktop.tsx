import logo from '../../assets/nis-logo-mark.png'
import {
  Checkbox,
  Divider,
  ErrorBanner,
  Field,
  HelpRow,
  PrimaryButton,
  SecondaryButton,
  SuccessPanel,
} from '../../ui/authFormParts'
import type { LoginFormState } from './useLoginForm'

export function LoginDesktop({
  form,
  onGoRegister,
  onGoHome,
}: {
  form: LoginFormState
  onGoRegister: () => void
  onGoHome: () => void
}) {
  return (
    <div className="af-desktop-page">
      <div className="af-header af-desktop-header">
        <img src={logo} alt="Nis3" className="af-logo" />
        <span className="af-brand">Nis3.</span>
      </div>

      <div className="af-desktop-card">
        {form.formVisible ? (
          <>
            <div className="af-desktop-title-block">
              <h1 className="af-title">Вход</h1>
              <p className="af-subtitle">Войдите в аккаунт Nis3, используя почту и пароль.</p>
            </div>

            <div className="af-desktop-fields">
              <Field
                label="Почта"
                type="email"
                value={form.email}
                onChange={form.setEmail}
                placeholder="you@nis.edu.kz"
                autoComplete="email"
              />
              <Field
                label="Пароль"
                type="password"
                value={form.password}
                onChange={form.setPassword}
                placeholder="Введите пароль"
                autoComplete="current-password"
              />

              <Checkbox
                checked={form.remember}
                onToggle={form.toggleRemember}
                label="Запомнить меня"
                labelFontSize={13.5}
              />

              {form.status === 'error' && form.errorMessage && (
                <ErrorBanner>{form.errorMessage}</ErrorBanner>
              )}

              <PrimaryButton
                label={form.connecting ? 'Входим…' : 'Войти'}
                connecting={form.connecting}
                disabled={form.submitDisabled}
                onClick={form.submit}
              />

              <Divider />

              <SecondaryButton label="Зарегистрироваться" onClick={onGoRegister} />

              <HelpRow />
            </div>
          </>
        ) : (
          <SuccessPanel message="Вход выполнен" onContinue={onGoHome} />
        )}
      </div>
    </div>
  )
}
