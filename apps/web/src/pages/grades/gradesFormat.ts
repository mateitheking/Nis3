const EMPTY_COLOR = '#5c5c5c'

// Пороги — ровно границы официальных оценок 2-5 (просьба пользователя
// 16 сентября 2026: 39.5/64.5/84.5, не круглые 40/65/85 — так проценты на
// самой границе округления попадают в ту же оценку, что и в СУШ).
const COLOR_5 = '#7fd88f' // зелёный
const COLOR_4 = '#d4af5a' // золотой (тот же --accent, что и везде в приложении)
const COLOR_3 = '#d97757' // красный (тот же --error) — раньше тут был оранжевый
const COLOR_2 = '#4a4a4a' // чёрный — не буквально #000: на тёмном фоне приложения
// он был бы неотличим от фона что текстом, что заливкой чипа

/** Тот же порог, что и в colorForPercent ниже — вынесен отдельно для
 * калькулятора «сколько нужно, чтобы получить N» (см. requiredScoreForTarget). */
export const MARK_THRESHOLDS: Record<number, number> = { 5: 84.5, 4: 64.5, 3: 39.5 }

export function colorForPercent(pct: number | null): string {
  if (pct == null) return EMPTY_COLOR
  if (pct >= 84.5) return COLOR_5
  if (pct >= 64.5) return COLOR_4
  if (pct >= 39.5) return COLOR_3
  return COLOR_2
}

/** Цвет текста ПОВЕРХ чипа, залитого цветом из colorForPercent. "Чёрный"
 * (COLOR_2) слишком тёмный для тёмного текста поверх — нужен светлый;
 * остальные цвета светлые/средние, тёмный текст на них читается как и на
 * золотых кнопках по всему приложению. */
export function textOnGradeColor(color: string): string {
  return color === COLOR_2 ? 'var(--text-primary)' : '#0a0a0a'
}

export function fmtNum(n: number): string {
  if (Number.isInteger(n)) return String(n)
  return Number(n).toFixed(2).replace(/0+$/, '').replace(/\.$/, '')
}

export function fmtPct(n: number, decimals: number): string {
  return n.toFixed(decimals) + '%'
}

export interface RequiredScoreResult {
  kind: string
  neededPercentOfKind: number
  achievable: boolean
  /** true — этот вид оценивания уже не участвует в решении: цель
   * обеспечена (или недостижима) независимо от результата по нему. */
  alreadyDecided: boolean
}

export interface WeakTopic {
  kind: string
  name: string
  score: number
  maxScore: number
  percent: number
}

/** Самые слабые темы предмета — по всем видам оценивания сразу (СОР и СОЧ
 * вперемешку, тема "нужно подтянуть" не зависит от того, в каком виде она
 * встретилась). Порог — тот же 64.5%, что и граница оценки "4" (см.
 * MARK_THRESHOLDS) — ниже него тема ещё не дотягивает до хорошей оценки.
 * Без тем без данных (max_score === 0 — не запланирована). */
export function weakestTopics(
  evaluations: { kind: string; topics: { name: string; score: number; max_score: number }[] }[],
  thresholdPercent = MARK_THRESHOLDS[4],
  limit = 4,
): WeakTopic[] {
  const all = evaluations.flatMap((ev) =>
    ev.topics
      .filter((t) => t.max_score > 0)
      .map((t) => ({
        kind: ev.kind, name: t.name, score: t.score, maxScore: t.max_score,
        percent: (t.score / t.max_score) * 100,
      })),
  )
  return all
    .filter((t) => t.percent < thresholdPercent)
    .sort((a, b) => a.percent - b.percent)
    .slice(0, limit)
}

/** Зеркало apps/api/grades.py::required_score_for_target — тот же расчёт,
 * просто на уже загруженных клиентом данных (не нужен лишний запрос к
 * серверу ради арифметики). Вес и заработанные баллы по ДРУГИМ видам
 * оценивания держим как есть, ``targetKind`` — единственная неизвестная. */
export function requiredScoreForTarget(
  evaluations: { kind: string; weight: number; earned: number; possible: number }[],
  targetKind: string,
  targetOverallPercent: number,
): RequiredScoreResult | null {
  const target = evaluations.find((e) => e.kind === targetKind)
  if (!target || target.weight <= 0) return null

  let otherContribution = 0
  for (const ev of evaluations) {
    if (ev.kind === targetKind) continue
    if (ev.possible > 0) otherContribution += (ev.earned / ev.possible) * ev.weight
  }

  const neededPercentOfKind = ((targetOverallPercent - otherContribution) / target.weight) * 100
  return {
    kind: targetKind,
    neededPercentOfKind,
    achievable: neededPercentOfKind >= 0 && neededPercentOfKind <= 100,
    alreadyDecided: neededPercentOfKind < 0 || neededPercentOfKind > 100,
  }
}
