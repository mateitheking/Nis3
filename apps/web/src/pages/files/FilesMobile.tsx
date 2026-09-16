import logo from '../../assets/nis-logo-mark.png'
import { initials } from '../../ui/dashboardParts'
import { BottomNav } from '../../ui/BottomNav'
import { AddTile, PhotoGrid } from './parts'
import type { FilesData } from './useFilesData'

export function FilesMobile({
  data,
  onNavigate,
}: {
  data: FilesData
  onNavigate: (key: string) => void
}) {
  const { me, photos, loading, uploading, error, upload, remove } = data

  return (
    <div className="files-mobile-page">
      <div className="files-mobile-header">
        <div className="sch-mobile-brand">
          <img src={logo} alt="Nis3" />
          <span>Nis3.</span>
        </div>
        <div className="sch-mobile-avatar">{initials(me?.display_name ?? '??')}</div>
      </div>

      <div className="files-mobile-titleblock">
        <h1>Файлы</h1>
        <p>Важные фото под рукой</p>
      </div>

      <div className="files-mobile-scroll">
        <PhotoGrid
          photos={photos}
          loading={loading}
          uploading={uploading}
          error={error}
          onDelete={remove}
        />
      </div>

      <AddTile mobile onPick={upload} />

      <BottomNav active="Файлы" onNavigate={onNavigate} />
    </div>
  )
}
