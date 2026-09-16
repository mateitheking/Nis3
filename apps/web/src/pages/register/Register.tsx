import { useMediaQuery } from '../../hooks/useMediaQuery'
import { RegisterDesktop } from './RegisterDesktop'
import { RegisterMobile } from './RegisterMobile'
import { useRegisterForm } from './useRegisterForm'

export function Register({
  onGoLogin,
  onGoHome,
}: {
  onGoLogin: () => void
  onGoHome: () => void
}) {
  const isDesktop = useMediaQuery('(min-width: 641px)')
  const form = useRegisterForm()

  return isDesktop ? (
    <RegisterDesktop form={form} onGoLogin={onGoLogin} onGoHome={onGoHome} />
  ) : (
    <RegisterMobile form={form} onGoLogin={onGoLogin} onGoHome={onGoHome} />
  )
}
