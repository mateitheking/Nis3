const WEEKDAYS = ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота']
const MONTHS = [
  'января', 'февраля', 'марта', 'апреля', 'мая', 'июня',
  'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря',
]
const WEEKDAY_SHORT = ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб']

/** '2026-09-15' -> Date, интерпретируется как локальная полночь, не UTC —
 * иначе в часовых поясах западнее UTC дата на экране сдвинулась бы на день
 * назад. */
export function parseIsoDate(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

export function formatWeekdayDate(iso: string): string {
  const d = parseIsoDate(iso)
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${WEEKDAY_SHORT[d.getDay()]}`
}

export function formatDayMonth(d: Date): string {
  return `${d.getDate()} ${MONTHS[d.getMonth()]}`
}

export function formatLongDate(iso: string): string {
  const d = parseIsoDate(iso)
  return `${WEEKDAYS[d.getDay()]}, ${String(d.getDate()).padStart(2, '0')} ${MONTHS[d.getMonth()]}`
}

/** 'через N дн.' — чистая арифметика от сегодняшней даты, сервер её не
 * считает (см. apps/api/main.py::events_upcoming). Капитализация первой
 * буквы намеренно не делается — 'среда' в фразе идёт после запятой. */
export function daysFromToday(iso: string): string {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const target = parseIsoDate(iso)
  const diffDays = Math.round((target.getTime() - today.getTime()) / 86_400_000)
  if (diffDays === 0) return 'сегодня'
  if (diffDays === 1) return 'завтра'
  if (diffDays < 0) return `${Math.abs(diffDays)} дн. назад`
  return `через ${diffDays} дн.`
}

/** Полный ISO datetime ('2026-09-10T09:30:00', без таймзоны — так его
 * отдаёт `datetime.isoformat()` в apps/api/main.py) -> '10 сентября, 09:30'.
 * Без смещения 'Z' в строке `new Date()` разбирает её как локальное время
 * браузера — этого достаточно, отдельного часового пояса сервер не несёт. */
export function formatMessageDateTime(iso: string): string {
  const d = new Date(iso)
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${hh}:${mm}`
}

/** Полный ISO datetime -> 'только что' / '5 мин назад' / '3 ч назад' /
 * '2 дн назад'. Намеренно без русского склонения по числу (не "5 минут"
 * вперемешку с "1 минута") — короткие неизменяемые сокращения ("мин", "ч",
 * "дн") читаются нормально в любом числе и проще, чем плюрализация. */
export function formatRelativeTime(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime()
  const diffMin = Math.floor(diffMs / 60_000)
  if (diffMin < 1) return 'только что'
  if (diffMin < 60) return `${diffMin} мин назад`
  const diffH = Math.floor(diffMin / 60)
  if (diffH < 24) return `${diffH} ч назад`
  const diffD = Math.floor(diffH / 24)
  return `${diffD} дн назад`
}

export function tomorrowIso(): string {
  const d = new Date()
  d.setDate(d.getDate() + 1)
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

export function formatShortDayMonth(iso: string): string {
  const d = parseIsoDate(iso)
  return `${String(d.getDate()).padStart(2, '0')}.${String(d.getMonth() + 1).padStart(2, '0')}`
}

export function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** Пн=0 .. Вс=6, а не JS-родной Вс=0..Сб=6 — школьная неделя считается с
 * понедельника. */
function mondayIndexedDow(d: Date): number {
  return (d.getDay() + 6) % 7
}

/** Если попали на выходной — ближайший будний день вперёд, как в дизайне
 * (Расписание.dc.html::nearestWeekday). Суббота/воскресенье не показывают
 * отдельно — 5-дневная школьная неделя, подтверждено на реальных данных
 * (aSc-фикстуры, docs/sources.md). */
export function nearestWeekday(d: Date): Date {
  const out = new Date(d)
  const dow = out.getDay()
  if (dow === 0) out.setDate(out.getDate() + 1)
  else if (dow === 6) out.setDate(out.getDate() + 2)
  return out
}

export function addWeekdays(d: Date, n: number): Date {
  const out = new Date(d)
  const step = n >= 0 ? 1 : -1
  let count = 0
  while (count !== n) {
    out.setDate(out.getDate() + step)
    const dow = out.getDay()
    if (dow !== 0 && dow !== 6) count += step
  }
  return out
}

/** Даты Пн..Пт той календарной недели, в которую попадает `d`. */
export function weekdayDates(d: Date): Date[] {
  const monday = new Date(d)
  monday.setDate(d.getDate() - mondayIndexedDow(d))
  return [0, 1, 2, 3, 4].map((i) => {
    const day = new Date(monday)
    day.setDate(monday.getDate() + i)
    return day
  })
}

export { mondayIndexedDow }

/** Часов до времени 'HH:MM' СЕГОДНЯ+offsetDays, округлено вниз. null, если
 * момент уже прошёл (не показываем отрицательный/нулевой отсчёт). */
export function hoursUntil(hhmm: string, offsetDays: number): number | null {
  const [h, m] = hhmm.split(':').map(Number)
  const target = new Date()
  target.setDate(target.getDate() + offsetDays)
  target.setHours(h, m, 0, 0)
  const diffMs = target.getTime() - Date.now()
  if (diffMs <= 0) return null
  return Math.round(diffMs / 3_600_000)
}
