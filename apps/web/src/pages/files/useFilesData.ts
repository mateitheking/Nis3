import { useCallback, useEffect, useState } from 'react'
import { useAccountShell } from '../../hooks/useAccountShell'
import { getJsonCached, invalidateCache } from '../../lib/apiCache'

export interface PhotoMeta {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  created_at: string
  url: string
  pos_x: number
  pos_y: number
  width: number
}

const PHOTOS_URL = '/api/photos'
export const DEFAULT_PHOTO_WIDTH = 170

export function useFilesData() {
  const shell = useAccountShell()
  const [photos, setPhotos] = useState<PhotoMeta[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const reload = useCallback(async (force = false) => {
    setLoading(true)
    setPhotos(await getJsonCached<PhotoMeta[]>(PHOTOS_URL, { force }))
    setLoading(false)
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  async function upload(file: File) {
    setUploading(true)
    setError(null)
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/photos', { method: 'POST', credentials: 'same-origin', body: form })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      setError(body.detail ?? `Не получилось загрузить (${res.status})`)
    } else {
      invalidateCache(PHOTOS_URL)
      await reload(true)
    }
    setUploading(false)
  }

  async function remove(id: string) {
    setPhotos((prev) => prev?.filter((p) => p.id !== id) ?? prev) // оптимистично, до ответа сервера
    const res = await fetch(`/api/photos/${id}`, { method: 'DELETE', credentials: 'same-origin' })
    invalidateCache(PHOTOS_URL)
    if (!res.ok) await reload(true) // не удалилось — вернуть как было
  }

  // Позиция на «столе» — обновляется на КАЖДЫЙ drop (не троттлится), но
  // запросов мало: одно перетаскивание = один PATCH по pointerup, не по
  // pointermove.
  async function move(id: string, posX: number, posY: number) {
    setPhotos((prev) => prev?.map((p) => (p.id === id ? { ...p, pos_x: posX, pos_y: posY } : p)) ?? prev)
    const res = await fetch(`/api/photos/${id}/position`, {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pos_x: posX, pos_y: posY }),
    })
    invalidateCache(PHOTOS_URL)
    if (!res.ok) await reload(true)
  }

  // Размер — тем же эндпоинтом, что и позиция (см. apps/api/main.py —
  // PhotoPositionBody, все поля опциональны), просто шлём только width.
  // Кнопка "вернуть исходный размер" — тот же вызов с DEFAULT_PHOTO_WIDTH.
  async function resize(id: string, width: number) {
    setPhotos((prev) => prev?.map((p) => (p.id === id ? { ...p, width } : p)) ?? prev)
    const res = await fetch(`/api/photos/${id}/position`, {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ width }),
    })
    invalidateCache(PHOTOS_URL)
    if (!res.ok) await reload(true)
  }

  return { ...shell, photos, loading, uploading, error, upload, remove, move, resize }
}

export type FilesData = ReturnType<typeof useFilesData>
