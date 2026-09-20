import { useState } from 'react'
import { Sidebar } from '../../ui/Sidebar'
import { SettingsDrawer } from '../../ui/SettingsDrawer'
import { ChatInput, ChatLog, ClearChatButton, NotConfiguredNotice } from './parts'
import type { AssistantData } from './useAssistantData'

export function AssistantDesktop({
  data,
  onNavigate,
  onLoggedOut,
}: {
  data: AssistantData
  onNavigate: (key: string) => void
  onLoggedOut: () => void
}) {
  const [settingsOpen, setSettingsOpen] = useState(false)
  const {
    me, sources, configured, messages, sending, error, send, clear, link, unlink, logout,
    updateName, uploadAvatar, deleteAvatar, changePassword, resendVerification,
  } = data
  const handleLogout = async () => {
    await logout()
    onLoggedOut()
  }

  return (
    <div className="home-desktop-page ai-page">
      <Sidebar
        active="NisAI"
        me={me}
        sources={sources}
        onNavigate={onNavigate}
        onOpenSettings={() => setSettingsOpen(true)}
      />

      <div className="home-main">
        <div className="home-main-inner">
          <div className="home-main-header">
            <span className="home-main-title">NisAI</span>
            <ClearChatButton onClear={clear} disabled={messages.length === 0} />
          </div>

          <div className="ai-shell">
            {configured === false ? (
              <NotConfiguredNotice />
            ) : (
              <>
                <ChatLog messages={messages} sending={sending} error={error} onStarterPick={send} />
                <ChatInput disabled={configured !== true} sending={sending} onSend={send} />
              </>
            )}
          </div>
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
        onResendVerification={resendVerification}
      />
    </div>
  )
}
