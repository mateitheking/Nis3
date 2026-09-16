import { useState } from 'react'
import { invalidateCache } from '../../lib/apiCache'
import { clearAssistantChat } from '../../lib/chatStorage'

type Status = 'idle' | 'connecting' | 'connected' | 'error'

export interface RegisterResult {
  student_id: string
  display_name: string
}

/**
 * Логика формы регистрации — общая для десктопного и мобильного макета
 * (см. useMediaQuery.ts, почему макетов два). В отличие от .dc.html-мокапа
 * (setTimeout, всегда успех), здесь настоящий POST /auth/register —
 * см. apps/api/main.py — и настоящие ответы сервера: 400 (плохие данные),
 * 409 (почта занята). Проверка "password === password2" — только клиентская
 * подсказка про опечатку, на сервер уходит один password (см. main.py —
 * там сознательно нет password2, это не граница безопасности).
 */
export function useRegisterForm() {
  const [status, setStatus] = useState<Status>('idle')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [password2, setPassword2] = useState('')
  const [agree, setAgree] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [result, setResult] = useState<RegisterResult | null>(null)

  const passwordsMismatch = password2.length > 0 && password !== password2
  const passwordTooShort = password.length > 0 && password.length < 8
  const connecting = status === 'connecting'

  const submitDisabled =
    connecting ||
    !name.trim() ||
    !email.trim() ||
    !password ||
    !password2 ||
    password !== password2 ||
    password.length < 8 ||
    !agree

  async function submit() {
    if (submitDisabled) return
    setStatus('connecting')
    setErrorMessage(null)
    try {
      const res = await fetch('/auth/register', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: name.trim(), email: email.trim(), password }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        throw new Error(body.detail || `Не получилось (${res.status})`)
      }
      invalidateCache() // см. useLoginForm.ts — тот же риск утечки кэша между аккаунтами
      clearAssistantChat()
      setResult(body as RegisterResult)
      setStatus('connected')
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : 'Не удалось связаться с сервером')
      setStatus('error')
    }
  }

  return {
    name,
    setName,
    email,
    setEmail,
    password,
    setPassword,
    password2,
    setPassword2,
    agree,
    toggleAgree: () => setAgree((a) => !a),
    status,
    connecting,
    connected: status === 'connected',
    formVisible: status !== 'connected',
    passwordsMismatch,
    passwordTooShort,
    submitDisabled,
    errorMessage,
    result,
    submit,
  }
}

export type RegisterFormState = ReturnType<typeof useRegisterForm>
