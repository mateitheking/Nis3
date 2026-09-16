import { useMediaQuery } from '../../hooks/useMediaQuery'
import { FilesDesktop } from './FilesDesktop'
import { FilesMobile } from './FilesMobile'
import { useFilesData } from './useFilesData'

export function Files({
  onNavigate,
  onLoggedOut,
}: {
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const isDesktop = useMediaQuery('(min-width: 900px)')
  const data = useFilesData()

  return isDesktop ? (
    <FilesDesktop data={data} onNavigate={onNavigate} onLoggedOut={onLoggedOut} />
  ) : (
    <FilesMobile data={data} onNavigate={onNavigate} />
  )
}
