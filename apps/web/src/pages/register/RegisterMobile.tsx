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
import type { RegisterFormState } from './useRegisterForm'

export function RegisterMobile({
  form,
  onGoLogin,
  onGoHome,
}: {
  form: RegisterFormState
  onGoLogin: () => void
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
              <h1 className="af-title af-title--mobile">Регистрация</h1>
              <p className="af-subtitle">
                Создайте аккаунт Nis3, чтобы получить доступ к расписанию, оценкам и файлам.
              </p>
            </div>

            <div className="af-mobile-fields">
              <Field
                mobile
                label="Имя"
                type="text"
                value={form.name}
                onChange={form.setName}
                placeholder="Айдана Смағұлова"
                autoComplete="name"
              />
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
                placeholder="Придумайте пароль"
                autoComplete="new-password"
                invalid={form.passwordTooShort}
                hint={form.passwordTooShort ? 'Минимум 8 символов' : undefined}
              />
              <Field
                mobile
                label="Повторите пароль"
                type="password"
                value={form.password2}
                onChange={form.setPassword2}
                placeholder="Повторите пароль"
                autoComplete="new-password"
                invalid={form.passwordsMismatch}
                hint={form.passwordsMismatch ? 'Пароли не совпадают' : undefined}
              />

              <Checkbox
                mobile
                checked={form.agree}
                onToggle={form.toggleAgree}
                label="Согласен с условиями использования и политикой конфиденциальности"
              />

              {form.status === 'error' && form.errorMessage && (
                <ErrorBanner>{form.errorMessage}</ErrorBanner>
              )}

              <Divider />

              <SecondaryButton mobile label="Уже есть аккаунт? Войти" onClick={onGoLogin} />

              <HelpRow mobile />
            </div>
          </>
        ) : (
          <SuccessPanel message="Аккаунт создан" onContinue={onGoHome} />
        )}
      </div>

      {form.formVisible && (
        <div className="af-mobile-footer">
          <PrimaryButton
            mobile
            label={form.connecting ? 'Создаём аккаунт…' : 'Зарегистрироваться'}
            connecting={form.connecting}
            disabled={form.submitDisabled}
            onClick={form.submit}
          />
        </div>
      )}
    </div>
  )
}
