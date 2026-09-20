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

  async function updateName(displayName: string): Promise<{ ok: boolean; error?: string }> {
    const res = await fetch('/api/me', {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_name: displayName }),
    })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) return { ok: false, error: data.detail ?? `Не получилось (${res.status})` }
    invalidateCache('/api/me')
    setMe(data)
    return { ok: true }
  }

  async function uploadAvatar(file: File): Promise<{ ok: boolean; error?: string }> {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/me/avatar', { method: 'POST', credentials: 'same-origin', body: form })
    const data = await res.json().catch(() => ({}))
    if (!res.ok) return { ok: false, error: data.detail ?? `Не получилось (${res.status})` }
    invalidateCache('/api/me')
    setMe(data)
    return { ok: true }
  }

  async function deleteAvatar() {
    const res = await fetch('/api/me/avatar', { method: 'DELETE', credentials: 'same-origin' })
    const data = await res.json().catch(() => ({}))
    invalidateCache('/api/me')
    if (res.ok) setMe(data)
  }

  async function changePassword(
    currentPassword: string,
    newPassword: string,
  ): Promise<{ ok: boolean; error?: string }> {
    const res = await fetch('/api/me/password', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
    })
    if (res.ok) return { ok: true }
    const data = await res.json().catch(() => ({}))
    return { ok: false, error: data.detail ?? `Не получилось (${res.status})` }
  }

  return {
    me, sources, link, unlink, logout, reloadSources,
    updateName, uploadAvatar, deleteAvatar, changePassword,
  }
}

export type AccountShell = ReturnType<typeof useAccountShell>
