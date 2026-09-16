// Общий кэш GET-запросов на всё приложение — in-memory Map поверх
// localStorage. Переключение Главная↔Расписание↔Оценки размонтирует и
// перемонтирует компоненты, но модульный Map и localStorage переживают
// это, в отличие от состояния хуков. localStorage поверх Map — не только
// ради переключения вкладок: без него самая обычная перезагрузка страницы
// (F5, не говоря про повторный заход) стирала Map целиком, и школьные
// источники (СУШ/EduPage) переспрашивались заново на каждый такой заход —
// живая жалоба 15 сентября 2026 после починки расписания: пользователь
// физически видел, как при каждом переключении вкладки браузера (не
// экрана внутри приложения — именно вкладки, т.е. новый заход) уходит
// пачка сетевых запросов. TTL в час — школьное расписание/оценки не
// меняются поминутно, а каждый лишний запрос к СУШ/EduPage — это ещё один
// шанс поймать капчу.
//
// Не путать с кэшем сессии источника на бэкенде (auth.py/db.py — куки,
// чтобы не логиниться заново) — это другой уровень, кэш самих ОТВЕТОВ API
// на клиенте, чтобы не переспрашивать сервер попусту.

interface CacheEntry<T> {
  data: T
  ts: number
}

interface FetchResult<T> {
  ok: boolean
  status: number
  data?: T
  detail?: string
}

const cache = new Map<string, CacheEntry<unknown>>()

const STORAGE_PREFIX = 'nis3:cache:'

/** localStorage может быть недоступен (приватная вкладка, отключён в
 * настройках браузера) или переполнен — в любом из случаев кэш просто не
 * переживёт перезагрузку, это не повод ронять страницу. */
function readPersisted<T>(url: string): CacheEntry<T> | null {
  try {
    const raw = localStorage.getItem(STORAGE_PREFIX + url)
    if (!raw) return null
    return JSON.parse(raw) as CacheEntry<T>
  } catch {
    return null
  }
}

function writePersisted<T>(url: string, entry: CacheEntry<T>): void {
  try {
    localStorage.setItem(STORAGE_PREFIX + url, JSON.stringify(entry))
  } catch {
    // переполнено/недоступно — переживаем без персистентности
  }
}

function removePersisted(url: string): void {
  try {
    localStorage.removeItem(STORAGE_PREFIX + url)
  } catch {
    // недоступно — нечего и удалять
  }
}

/** in-memory Map — источник истины на время жизни вкладки; если записи там
 * нет (свежая перезагрузка страницы), пробуем поднять из localStorage и
 * прогреть Map, чтобы повторные чтения в этой же вкладке не били по диску
 * заново. */
function getEntry<T>(url: string): CacheEntry<T> | undefined {
  const inMemory = cache.get(url) as CacheEntry<T> | undefined
  if (inMemory) return inMemory
  const persisted = readPersisted<T>(url)
  if (persisted) cache.set(url, persisted)
  return persisted ?? undefined
}

function setEntry<T>(url: string, entry: CacheEntry<T>): void {
  cache.set(url, entry)
  writePersisted(url, entry)
}

/** Дедупликация одновременных запросов на один URL — живой баг 14 сентября
 * 2026: React StrictMode в dev-режиме нарочно вызывает эффекты дважды
 * подряд (mount → unmount → mount, чтобы ловить пропущенный cleanup), и
 * оба вызова getJsonCached('/api/grades') успевали стартовать ДО того, как
 * первый положит ответ в cache — оба бились в сеть параллельно. Для СУШ
 * это было не просто лишним запросом: если в этот момент закэшированной
 * сессии ещё не было, оба параллельных запроса independently логинились,
 * а СУШ не даёт параллельных сессий одного аккаунта — второй логин
 * обрывал первый, и на следующий реальный запрос СУШ отвечал «сессия
 * завершена входом с другой рабочей станции». Выглядело как сторонний
 * вход, а было — наше же приложение само с собой. Пока запрос на URL уже
 * летит, второй вызов просто ждёт тот же промис, а не открывает новый. */
const inFlight = new Map<string, Promise<FetchResult<unknown>>>()

/** Час — школьное расписание/оценки не меняются ежеминутно, и каждый
 * лишний запрос к СУШ/EduPage — лишний шанс на капчу (см. комментарий
 * вверху файла). Действие, которое реально должно быть видно сразу
 * (привязка источника, загрузка фото), само зовёт invalidateCache. */
const DEFAULT_TTL_MS = 60 * 60_000

async function fetchDeduped<T>(url: string): Promise<FetchResult<T>> {
  const pending = inFlight.get(url) as Promise<FetchResult<T>> | undefined
  if (pending) return pending

  const promise = (async (): Promise<FetchResult<T>> => {
    const res = await fetch(url, { credentials: 'same-origin' })
    if (!res.ok) {
      cache.delete(url) // не кэшируем ошибки — иначе "не привязан" залипнет после привязки
      removePersisted(url)
      const body = await res.json().catch(() => ({}))
      return { ok: false, status: res.status, detail: body.detail ?? `Ошибка ${res.status}` }
    }
    const data = (await res.json()) as T
    setEntry(url, { data, ts: Date.now() })
    return { ok: true, status: res.status, data }
  })()

  inFlight.set(url, promise as Promise<FetchResult<unknown>>)
  try {
    return await promise
  } finally {
    inFlight.delete(url)
  }
}

export async function getJsonCached<T>(
  url: string,
  opts?: { ttlMs?: number; force?: boolean },
): Promise<T | null> {
  const ttl = opts?.ttlMs ?? DEFAULT_TTL_MS
  if (!opts?.force) {
    const entry = getEntry<T>(url)
    if (entry && Date.now() - entry.ts < ttl) {
      return entry.data
    }
  }
  const res = await fetchDeduped<T>(url)
  return res.ok ? (res.data as T) : null
}

export type JsonResult<T> = { ok: true; data: T } | { ok: false; status: number; detail: string }

/** То же самое, но с деталями ошибки вместо null — нужно Оценкам, где
 * "нет данных" (400 от источника) и "СУШ не привязан" — разные сообщения
 * пользователю, а не одно общее "не получилось". Тот же кэш, тот же TTL. */
export async function getJsonWithDetail<T>(
  url: string,
  opts?: { ttlMs?: number; force?: boolean },
): Promise<JsonResult<T>> {
  const ttl = opts?.ttlMs ?? DEFAULT_TTL_MS
  if (!opts?.force) {
    const entry = getEntry<T>(url)
    if (entry && Date.now() - entry.ts < ttl) {
      return { ok: true, data: entry.data }
    }
  }
  const res = await fetchDeduped<T>(url)
  return res.ok
    ? { ok: true, data: res.data as T }
    : { ok: false, status: res.status, detail: res.detail ?? `Ошибка ${res.status}` }
}

/** Позвать после любого действия, которое меняет то, что отдаёт GET
 * (привязка/отвязка источника, загрузка/удаление фото, вход/выход) —
 * иначе кэш покажет старое ещё DEFAULT_TTL_MS, а на выходе из аккаунта —
 * рискует показать следующему вошедшему данные предыдущего. `prefix` —
 * точный URL или его начало (например '/api/photos' снесёт и сам список,
 * и что угодно с этим префиксом); без аргумента чистит всё, включая
 * localStorage. */
export function invalidateCache(prefix?: string): void {
  if (!prefix) {
    cache.clear()
    try {
      for (let i = localStorage.length - 1; i >= 0; i--) {
        const key = localStorage.key(i)
        if (key?.startsWith(STORAGE_PREFIX)) localStorage.removeItem(key)
      }
    } catch {
      // недоступен — в памяти уже почищено, переживаем без persisted-части
    }
    return
  }
  for (const key of cache.keys()) {
    if (key.startsWith(prefix)) cache.delete(key)
  }
  try {
    for (let i = localStorage.length - 1; i >= 0; i--) {
      const key = localStorage.key(i)
      if (key?.startsWith(STORAGE_PREFIX + prefix)) localStorage.removeItem(key)
    }
  } catch {
    // недоступен — то же самое
  }
}
