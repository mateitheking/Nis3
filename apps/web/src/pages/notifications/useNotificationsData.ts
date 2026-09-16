import { useCallback, useEffect, useState } from 'react'
import { useAccountShell } from '../../hooks/useAccountShell'
import { getJsonWithDetail } from '../../lib/apiCache'
import type { NotificationItem } from '../../types'

/** Полная лента (see: home/useHomeData.ts грузит только превью через тот
 * же /api/notifications с меньшим limit — сюда за полным списком). */
export function useNotificationsData() {
  const shell = useAccountShell()
  const [items, setItems] = useState<NotificationItem[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    const res = await getJsonWithDetail<NotificationItem[]>('/api/notifications?limit=100')
    if (res.ok) {
      setItems(res.data)
      setError(null)
    } else {
      setItems(null)
      setError(res.detail)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  return { ...shell, items, error, loading }
}

export type NotificationsData = ReturnType<typeof useNotificationsData>
