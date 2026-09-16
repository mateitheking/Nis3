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

export function LoginMobile({
  form,
  onGoRegister,
  onGoHome,
}: {
  form: LoginFormState
  onGoRegister: () => void
  onGoHome: () => void
}) {
  return (
    <div className="af-mobile-page">
      <div className="af-header af-mobile-header">
        <img src={logo} alt="Nis3" className="af-logo af-logo--mobile" />
        <span className="af-brand af-brand--mobile">Nis3.</span>
      </div>

      <div className="af-mobile-scroll">
        {form.formVisible ? (
          <>
            <div className="af-mobile-title-block">
              <h1 className="af-title af-title--mobile">Вход</h1>
              <p className="af-subtitle">Войдите в аккаунт Nis3, используя почту и пароль.</p>
            </div>

            <div className="af-mobile-fields">
              <Field
                mobile
                label="Почта"
                type="email"
                value={form.email}
                onChange={form.setEmail}
                placeholder="you@nis.edu.kz"
                autoComplete="email"
              />
              <Field
                mobile
                label="Пароль"
                type="password"
                value={form.password}
                onChange={form.setPassword}
                placeholder="Введите пароль"
                autoComplete="current-password"
              />

              <Checkbox
                mobile
                checked={form.remember}
                onToggle={form.toggleRemember}
                label="Запомнить меня"
                labelFontSize={14}
              />

              {form.status === 'error' && form.errorMessage && (
                <ErrorBanner>{form.errorMessage}</ErrorBanner>
              )}

              <Divider />

              <SecondaryButton mobile label="Зарегистрироваться" onClick={onGoRegister} />

              <HelpRow mobile />
            </div>
          </>
        ) : (
          <SuccessPanel message="Вход выполнен" onContinue={onGoHome} />
        )}
      </div>

      {form.formVisible && (
        <div className="af-mobile-footer">
          <PrimaryButton
            mobile
            label={form.connecting ? 'Входим…' : 'Войти'}
            connecting={form.connecting}
            disabled={form.submitDisabled}
            onClick={form.submit}
          />
        </div>
      )}
    </div>
  )
}
