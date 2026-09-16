import { useMediaQuery } from '../../hooks/useMediaQuery'
import { GradesDesktop } from './GradesDesktop'
import { GradesMobile } from './GradesMobile'
import { useGradesData } from './useGradesData'

export function Grades({
  onNavigate,
  onLoggedOut,
}: {
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const isDesktop = useMediaQuery('(min-width: 900px)')
  const data = useGradesData()

  return isDesktop ? (
    <GradesDesktop data={data} onNavigate={onNavigate} onLoggedOut={onLoggedOut} />
  ) : (
    <GradesMobile data={data} onNavigate={onNavigate} />
  )
}
