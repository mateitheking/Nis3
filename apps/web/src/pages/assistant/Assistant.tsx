import { useMediaQuery } from '../../hooks/useMediaQuery'
import { AssistantDesktop } from './AssistantDesktop'
import { AssistantMobile } from './AssistantMobile'
import { useAssistantData } from './useAssistantData'

export function Assistant({
  onNavigate,
  onLoggedOut,
}: {
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const isDesktop = useMediaQuery('(min-width: 900px)')
  const data = useAssistantData()

  return isDesktop ? (
    <AssistantDesktop data={data} onNavigate={onNavigate} onLoggedOut={onLoggedOut} />
  ) : (
    <AssistantMobile data={data} onNavigate={onNavigate} />
  )
}
