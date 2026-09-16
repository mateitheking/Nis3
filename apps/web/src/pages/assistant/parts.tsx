import { useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '../../lib/chatStorage'

export function NotConfiguredNotice() {
  return (
    <div className="ai-empty">
      <span className="ai-empty-icon">AI</span>
      <div className="ai-empty-title">NisAI ещё не подключён</div>
      <p className="ai-empty-text">
        Ключ для ассистента добавят чуть позже — как только это случится, здесь сразу заработает чат.
      </p>
    </div>
  )
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === 'user'
  return (
    <div className={`ai-row${isUser ? ' is-user' : ''}`}>
      {!isUser && <span className="ai-avatar">AI</span>}
      <div className={`ai-bubble${isUser ? ' is-user' : ''}`}>{message.content}</div>
    </div>
  )
}

function TypingBubble() {
  return (
    <div className="ai-row">
      <span className="ai-avatar">AI</span>
      <div className="ai-bubble ai-typing">
        <span />
        <span />
        <span />
      </div>
    </div>
  )
}

const STARTER_PROMPTS = [
  'Что у меня сегодня по расписанию?',
  'Какие оценки у меня сейчас?',
  'Сколько нужно набрать за СОЧ по математике на пятёрку?',
  'Когда ближайший СОР?',
]

export function ChatLog({
  messages,
  sending,
  error,
  onStarterPick,
}: {
  messages: ChatMessage[]
  sending: boolean
  error: string | null
  onStarterPick: (text: string) => void
}) {
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    endRef.current?.scrollIntoView({ block: 'end' })
  }, [messages.length, sending])

  if (messages.length === 0) {
    return (
      <div className="ai-log ai-log-empty">
        <span className="ai-avatar ai-avatar-big">AI</span>
        <div className="ai-empty-title">Привет! Я NisAI</div>
        <p className="ai-empty-text">
          Спрашивай про расписание, оценки и что нужно набрать за СОР/СОЧ — я отвечаю, только
          заглянув в твои настоящие данные, а не гадая.
        </p>
        <div className="ai-starters">
          {STARTER_PROMPTS.map((p) => (
            <button type="button" className="ai-starter" key={p} onClick={() => onStarterPick(p)}>
              {p}
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="ai-log">
      {messages.map((m, i) => (
        <Bubble message={m} key={i} />
      ))}
      {sending && <TypingBubble />}
      {error && <div className="ai-error">{error}</div>}
      <div ref={endRef} />
    </div>
  )
}

export function ChatInput({
  disabled,
  sending,
  onSend,
}: {
  disabled: boolean
  sending: boolean
  onSend: (text: string) => void
}) {
  const [value, setValue] = useState('')
  const areaRef = useRef<HTMLTextAreaElement>(null)

  function submit() {
    if (!value.trim() || sending) return
    onSend(value)
    setValue('')
    requestAnimationFrame(() => {
      if (areaRef.current) areaRef.current.style.height = 'auto'
    })
  }

  return (
    <div className="ai-input-row">
      <textarea
        ref={areaRef}
        className="ai-input"
        placeholder={disabled ? 'NisAI ещё не подключён' : 'Спроси что-нибудь…'}
        value={value}
        disabled={disabled}
        rows={1}
        onChange={(e) => {
          setValue(e.target.value)
          e.target.style.height = 'auto'
          e.target.style.height = `${Math.min(e.target.scrollHeight, 140)}px`
        }}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault()
            submit()
          }
        }}
      />
      <button
        type="button"
        className="ai-send-btn"
        onClick={submit}
        disabled={disabled || sending || !value.trim()}
        aria-label="Отправить"
        title="Отправить"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="#0a0a0a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width="18" height="18">
          <path d="M5 12h14M13 6l6 6-6 6" />
        </svg>
      </button>
    </div>
  )
}

export function ClearChatButton({ onClear, disabled }: { onClear: () => void; disabled: boolean }) {
  if (disabled) return null
  return (
    <button type="button" className="ai-clear-btn" onClick={onClear} title="Очистить переписку">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" width="15" height="15">
        <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
      </svg>
      Очистить
    </button>
  )
}
