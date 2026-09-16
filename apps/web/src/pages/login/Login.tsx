import { useMediaQuery } from '../../hooks/useMediaQuery'
import { LoginDesktop } from './LoginDesktop'
import { LoginMobile } from './LoginMobile'
import { useLoginForm } from './useLoginForm'

export function Login({
  onGoRegister,
  onGoHome,
}: {
  onGoRegister: () => void
  onGoHome: () => void
}) {
  const isDesktop = useMediaQuery('(min-width: 641px)')
  const form = useLoginForm()

  return isDesktop ? (
    <LoginDesktop form={form} onGoRegister={onGoRegister} onGoHome={onGoHome} />
  ) : (
    <LoginMobile form={form} onGoRegister={onGoRegister} onGoHome={onGoHome} />
  )
}
