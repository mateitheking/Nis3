import { useState } from 'react'
import { Sidebar } from '../../ui/Sidebar'
import { SettingsDrawer } from '../../ui/SettingsDrawer'
import { AddButton, DesktopBoardArea } from './parts'
import type { FilesData } from './useFilesData'

export function FilesDesktop({
  data,
  onNavigate,
  onLoggedOut,
}: {
  data: FilesData
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [editMode, setEditMode] = useState(false)
  const {
    me, sources, photos, loading, uploading, error, upload, remove, move, resize, link, unlink, logout,
    updateName, uploadAvatar, deleteAvatar, changePassword,
  } = data
  const handleLogout = async () => {
    await logout()
    onLoggedOut()
  }

  return (
    <div className="home-desktop-page">
      <Sidebar
        active="Файлы"
        me={me}
        sources={sources}
        onNavigate={onNavigate}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <div className="home-main">
        <div className="home-main-inner">
          <div className="home-main-header">
            <span className="home-main-title">Файлы</span>
            <div className="files-header-actions">
              <AddButton onPick={upload} />
              <button
                type="button"
                className={`files-edit-toggle${editMode ? ' is-active' : ''}`}
                onClick={() => setEditMode((v) => !v)}
              >
                {editMode ? 'Готово' : 'Редактировать'}
              </button>
            </div>
          </div>

          <DesktopBoardArea
            photos={photos}
            loading={loading}
            uploading={uploading}
            error={error}
            editMode={editMode}
            onUpload={upload}
            onDelete={remove}
            onMove={move}
            onResize={resize}
          />
        </div>
      </div>

      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        variant="desktop"
        me={me}
        sources={sources}
        onUnlink={unlink}
        onLink={link}
        onLogout={handleLogout}
        onUpdateName={updateName}
        onUpdateAvatar={uploadAvatar}
        onDeleteAvatar={deleteAvatar}
        onChangePassword={changePassword}
      />
    </div>
  )
}
