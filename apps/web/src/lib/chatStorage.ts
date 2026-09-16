// История чата NisAI — sessionStorage, не localStorage: в отличие от
// расписания/оценок (apiCache.ts, час, переживает перезагрузку) переписка
// с ассистентом живёт только вкладку — не стоит копить её на диске дольше,
// чем нужно. sessionStorage, а не React-состояние — потому что App.tsx
// полностью размонтирует экран при переходе на другой (см. App.tsx), и
// обычный useState стёр бы диалог при любом клике в сайдбаре и возврате.

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

const KEY = 'nis3:nisai:chat'

export function loadChat(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

export function saveChat(messages: ChatMessage[]): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify(messages))
  } catch {
    // недоступно/переполнено — переживаем без персистентности
  }
}

/** Звать при входе/регистрации/выходе — как invalidateCache() в
 * apiCache.ts, той же причиной: общий браузер не должен показывать
 * следующему вошедшему переписку предыдущего ученика. */
export function clearAssistantChat(): void {
  try {
    sessionStorage.removeItem(KEY)
  } catch {
    // нечего удалять
  }
}
