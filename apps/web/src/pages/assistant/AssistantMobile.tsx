import logo from '../../assets/nis-logo-mark.png'
import { Avatar } from '../../ui/dashboardParts'
import { BottomNav } from '../../ui/BottomNav'
import { ChatInput, ChatLog, ClearChatButton, NotConfiguredNotice } from './parts'
import type { AssistantData } from './useAssistantData'

export function AssistantMobile({
  data,
  onNavigate,
}: {
  data: AssistantData
  onNavigate: (key: string) => void
}) {
  const { me, configured, messages, sending, error, send, clear } = data

  return (
    <div className="files-mobile-page">
      <div className="files-mobile-header">
        <div className="sch-mobile-brand">
          <img src={logo} alt="Nis3" />
          <span>Nis3.</span>
        </div>
        <Avatar name={me?.display_name ?? '??'} size={34} avatarUrl={me?.avatar_url} />
      </div>

      <div className="files-mobile-titleblock ai-mobile-titleblock">
        <h1>NisAI</h1>
        <ClearChatButton onClear={clear} disabled={messages.length === 0} />
      </div>

      {configured === false ? (
        <NotConfiguredNotice />
      ) : (
        <>
          <ChatLog messages={messages} sending={sending} error={error} onStarterPick={send} />
          <ChatInput disabled={configured !== true} sending={sending} onSend={send} />
        </>
      )}

      <BottomNav active="NisAI" onNavigate={onNavigate} />
    </div>
  )
}
