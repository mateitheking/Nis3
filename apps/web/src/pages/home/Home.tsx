import { useMediaQuery } from '../../hooks/useMediaQuery'
import { HomeDesktop } from './HomeDesktop'
import { HomeMobile } from './HomeMobile'
import { useHomeData } from './useHomeData'

export function Home({
  onNavigate,
  onLoggedOut,
}: {
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const isDesktop = useMediaQuery('(min-width: 900px)')
  const data = useHomeData()

  return isDesktop ? (
    <HomeDesktop data={data} onNavigate={onNavigate} onLoggedOut={onLoggedOut} />
  ) : (
    <HomeMobile data={data} onNavigate={onNavigate} onLoggedOut={onLoggedOut} />
  )
}
