import { useEffect, useRef, useState } from 'react'
import { useAccountShell } from '../../hooks/useAccountShell'
import { type ChatMessage, loadChat, saveChat } from '../../lib/chatStorage'

export function useAssistantData() {
  const shell = useAccountShell()
  // Не через apiCache/getJsonCached: это не школьный источник (СУШ/EduPage),
  // которого стоит беречь от лишних запросов — просто чтение переменной
  // окружения на сервере, и статус должен быть точным сразу после того, как
  // ключ подключат, а не залипать на "не настроен" до истечения TTL.
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>(() => loadChat())
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const seq = useRef(0)

  useEffect(() => {
    const mySeq = ++seq.current
    fetch('/api/assistant/status', { credentials: 'same-origin' })
      .then((res) => (res.ok ? res.json() : { configured: false }))
      .then((body) => {
        if (mySeq === seq.current) setConfigured(Boolean(body.configured))
      })
      .catch(() => {
        if (mySeq === seq.current) setConfigured(false)
      })
  }, [])

  useEffect(() => {
    saveChat(messages)
  }, [messages])

  async function send(text: string) {
    const message = text.trim()
    if (!message || sending) return
    setError(null)
    const history = messages
    setMessages((prev) => [...prev, { role: 'user', content: message }])
    setSending(true)
    try {
      const res = await fetch('/api/assistant/chat', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history, message }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(body.detail || `Не получилось (${res.status})`)
      }
      setMessages((prev) => [...prev, { role: 'assistant', content: String(body.reply ?? '') }])
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Не удалось связаться с сервером')
    } finally {
      setSending(false)
    }
  }

  function clear() {
    setMessages([])
    setError(null)
  }

  return { ...shell, configured, messages, sending, error, send, clear }
}

export type AssistantData = ReturnType<typeof useAssistantData>
