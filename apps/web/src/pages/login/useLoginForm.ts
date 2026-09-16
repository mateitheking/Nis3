import { useState } from 'react'
import { invalidateCache } from '../../lib/apiCache'
import { clearAssistantChat } from '../../lib/chatStorage'

type Status = 'idle' | 'connecting' | 'connected' | 'error'

export interface LoginResult {
  student_id: string
  display_name: string
}

/** Логика формы входа — POST /auth/login, см. apps/api/main.py. 'remember'
 * реально влияет на куку (сессионная vs 14 дней), не декоративный чекбокс —
 * см. main.py::_set_session_cookie. */
export function useLoginForm() {
  const [status, setStatus] = useState<Status>('idle')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [remember, setRemember] = useState(true)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [result, setResult] = useState<LoginResult | null>(null)

  const connecting = status === 'connecting'
  const submitDisabled = connecting || !email.trim() || !password

  async function submit() {
    if (submitDisabled) return
    setStatus('connecting')
    setErrorMessage(null)
    try {
      const res = await fetch('/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim(), password, remember }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(body.detail || `Не получилось (${res.status})`)
      }
      // На общем браузере логин без предшествующего logout() (сессия
      // истекла молча, не через кнопку «Выйти») иначе оставлял бы кэш
      // прошлого ученика в localStorage — теперь он живёт час и
      // переживает перезагрузку (см. lib/apiCache.ts), так что это уже не
      // "покажет неправильное на пару минут", а реальная утечка данных
      // одного ученика следующему.
      invalidateCache()
      clearAssistantChat()
      setResult(body as LoginResult)
      setStatus('connected')
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Не удалось связаться с сервером')
      setStatus('error')
    }
  }

  return {
    email,
    setEmail,
    password,
    setPassword,
    remember,
    toggleRemember: () => setRemember((r) => !r),
    status,
    connecting,
    connected: status === 'connected',
    formVisible: status !== 'connected',
    submitDisabled,
    errorMessage,
    result,
    submit,
  }
}

export type LoginFormState = ReturnType<typeof useLoginForm>
