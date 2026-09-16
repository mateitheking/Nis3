import { useMediaQuery } from '../../hooks/useMediaQuery'
import { ScheduleDesktop } from './ScheduleDesktop'
import { ScheduleMobile } from './ScheduleMobile'
import { useScheduleData } from './useScheduleData'

export function Schedule({
  onNavigate,
  onLoggedOut,
}: {
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const isDesktop = useMediaQuery('(min-width: 900px)')
  const data = useScheduleData()

  return isDesktop ? (
    <ScheduleDesktop data={data} onNavigate={onNavigate} onLoggedOut={onLoggedOut} />
  ) : (
    <ScheduleMobile data={data} onNavigate={onNavigate} />
  )
}
