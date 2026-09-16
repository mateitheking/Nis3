import { useEffect, useState } from 'react'
import { getJsonCached, invalidateCache } from '../lib/apiCache'
import { clearAssistantChat } from '../lib/chatStorage'
import type { Me, SourcesStatus } from '../types'

export interface LinkFields {
  school: string // school-код (СУШ) / поддомен (EduPage)
  username: string // ИИН (СУШ) / логин (EduPage)
  password: string
}

export interface LinkResult {
  ok: boolean
  sessionOk?: boolean
  reason?: string
  error?: string
}

/** Профиль + статус источников + привязать/отвязать/выйти — общее для
 * настроек на всех экранах (Главная/Расписание/Оценки/Файлы), чтобы не
 * дублировать один и тот же fetch в каждом page-хуке. */
export function useAccountShell() {
  const [me, setMe] = useState<Me | null>(null)
  const [sources, setSources] = useState<SourcesStatus | null>(null)

  async function reloadSources(force = false) {
    setSources(await getJsonCached<SourcesStatus>('/api/sources/status', { force }))
  }

  useEffect(() => {
    getJsonCached<Me>('/api/me').then(setMe)
    reloadSources()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function link(source: 'sush' | 'edupage', fields: LinkFields): Promise<LinkResult> {
    const body =
      source === 'sush'
        ? { school: fields.school, iin: fields.username, password: fields.password }
        : { subdomain: fields.school, username: fields.username, password: fields.password }
    const res = await fetch(`/auth/link/${source}`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await res.json().catch(() => ({}))
    // Привязка источника меняет не только статус — все экраны, которые
    // раньше честно отвечали "не привязан", должны перечитать реальные
    // данные, а не досидеть на закэшированной пустоте до истечения TTL.
    invalidateCache()
    if (!res.ok) {
      await reloadSources(true)
      return { ok: false, error: data.detail ?? `Не получилось (${res.status})` }
    }
    await reloadSources(true)
    return { ok: true, sessionOk: data.session_ok, reason: data.reason }
  }

  async function unlink(source: 'sush' | 'edupage') {
    await fetch(`/auth/link/${source}`, { method: 'DELETE', credentials: 'same-origin' })
    invalidateCache()
    await reloadSources(true)
  }

  async function logout() {
    await fetch('/auth/logout', { method: 'POST', credentials: 'same-origin' })
    invalidateCache()
    clearAssistantChat()
  }

  return { me, sources, link, unlink, logout, reloadSources }
}

export type AccountShell = ReturnType<typeof useAccountShell>
