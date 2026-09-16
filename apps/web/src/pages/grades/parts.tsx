import { useState } from 'react'
import type { GradeEvaluation, GradeSubject } from '../../types'
import {
  MARK_THRESHOLDS,
  colorForPercent,
  fmtNum,
  fmtPct,
  requiredScoreForTarget,
  textOnGradeColor,
  weakestTopics,
} from './gradesFormat'

export function QuarterTabs({ quarter, onChange }: { quarter: number; onChange: (q: number) => void }) {
  const labels = ['I', 'II', 'III', 'IV']
  return (
    <div className="gr-tabs">
      {labels.map((label, i) => {
        const q = i + 1
        return (
          <button
            key={q}
            type="button"
            className={`gr-tab${q === quarter ? ' is-active' : ''}`}
            onClick={() => onChange(q)}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}

export function YearNav({ label, onPrev, onNext }: { label: string; onPrev: () => void; onNext: () => void }) {
  return (
    <div className="gr-yearnav">
      <button type="button" className="gr-yearnav-btn" onClick={onPrev} aria-label="Предыдущий год">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
          <path d="M15 18l-6-6 6-6" />
        </svg>
      </button>
      <span className="gr-yearnav-label">{label}</span>
      <button type="button" className="gr-yearnav-btn" onClick={onNext} aria-label="Следующий год">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width="12" height="12">
          <path d="M9 18l6-6-6-6" />
        </svg>
      </button>
    </div>
  )
}

export function SubjectCard({
  subject,
  active,
  onClick,
}: {
  subject: GradeSubject
  active: boolean
  onClick: () => void
}) {
  const hasData = subject.evaluations.length > 0
  const color = colorForPercent(hasData ? subject.score : null)
  return (
    <button type="button" className={`gr-card${active ? ' is-active' : ''}`} onClick={onClick}>
      <div className="gr-card-name">{subject.name}</div>
      {hasData ? (
        <>
          <div className="gr-card-row">
            <span className="gr-card-percent" style={{ color }}>
              {fmtPct(subject.score, 2)}
            </span>
            <span className="gr-card-marklabel">
              оценка <span style={{ color: subject.mark ? color : 'var(--text-tertiary)', fontWeight: 800 }}>
                {subject.mark || '—'}
              </span>
            </span>
          </div>
          <div className="gr-bar">
            <div className="gr-bar-fill" style={{ width: `${subject.score}%`, background: color }} />
          </div>
        </>
      ) : (
        <div className="gr-card-row">
          <span className="gr-card-noplan">Ещё не запланировано</span>
          <span className="gr-card-noplan">оценка —</span>
        </div>
      )}
    </button>
  )
}

function EvaluationTopics({
  ev,
  calcOpen,
  overrides,
  onOverride,
}: {
  ev: GradeEvaluation
  calcOpen: boolean
  overrides: Map<string, number>
  onOverride: (key: string, value: number) => void
}) {
  if (ev.topics.length === 0) {
    return <div className="gr-eval-noplan">Не запланировано в этой четверти</div>
  }
  const earnedNow = calcOpen
    ? ev.topics.reduce((sum, t, i) => sum + (overrides.get(`${ev.kind}_${i}`) ?? t.score), 0)
    : ev.earned
  const pctNow = ev.possible > 0 ? (earnedNow / ev.possible) * 100 : 0
  return (
    <>
      <div className="gr-eval-summary">
        {fmtNum(earnedNow)} / {fmtNum(ev.possible)} · {fmtPct(pctNow, 1)}
      </div>
      <div className="gr-topics">
        {ev.topics.map((t, i) => {
          const key = `${ev.kind}_${i}`
          const value = overrides.get(key) ?? t.score
          return (
            <div className="gr-topic-row" key={key}>
              <span className="gr-topic-name">{t.name}</span>
              {calcOpen ? (
                <div className="gr-stepper">
                  <button
                    type="button"
                    className="gr-step-btn"
                    onClick={() => onOverride(key, Math.max(0, value - 1))}
                  >
                    −
                  </button>
                  <span className="gr-step-value">{fmtNum(value)}</span>
                  <button
                    type="button"
                    className="gr-step-btn"
                    onClick={() => onOverride(key, Math.min(t.max_score, value + 1))}
                  >
                    +
                  </button>
                  <span className="gr-step-max">/ {fmtNum(t.max_score)}</span>
                </div>
              ) : (
                <span className="gr-topic-score">
                  {fmtNum(t.score)} / {fmtNum(t.max_score)}
                </span>
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}

/** Краткий разбор "что подтянуть" — самые слабые темы предмета по факту
 * набранных баллов (не по прогнозу, в отличие от gr-ask-card ниже), ниже
 * границы оценки "4". Просьба пользователя 16 сентября 2026. */
function WeakTopicsCard({ evaluations }: { evaluations: GradeEvaluation[] }) {
  const weak = weakestTopics(evaluations)
  return (
    <div className="gr-weak-card">
      <div className="gr-weak-title">Стоит подтянуть</div>
      {weak.length === 0 ? (
        <div className="gr-weak-empty">Слабых тем не нашлось — по всем темам от {fmtNum(MARK_THRESHOLDS[4])}% и выше</div>
      ) : (
        <div className="gr-weak-list">
          {weak.map((t, i) => (
            <div className="gr-weak-row" key={`${t.kind}_${t.name}_${i}`}>
              <span className="gr-weak-name">
                {t.name} <span className="gr-weak-kind">· {t.kind}</span>
              </span>
              <span className="gr-weak-value" style={{ color: colorForPercent(t.percent) }}>
                {fmtNum(t.score)} / {fmtNum(t.maxScore)} ({fmtPct(t.percent, 0)})
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function SubjectDetail({
  subject,
  loading,
}: {
  subject: GradeSubject | null
  loading: boolean
}) {
  const [calcOpen, setCalcOpen] = useState(false)
  const [overrides, setOverrides] = useState<Map<string, number>>(new Map())
  const [targetMark, setTargetMark] = useState<number | null>(null)

  if (!subject) return null

  const hasEvals = subject.evaluations.length > 0
  const hasData = hasEvals
  const totalWeight = subject.evaluations.reduce((sum, ev) => sum + ev.weight, 0) || 100

  function pctOf(ev: GradeEvaluation): number {
    if (ev.possible === 0) return 0
    if (!calcOpen) return (ev.earned / ev.possible) * 100
    const earnedNow = ev.topics.reduce((sum, t, i) => sum + (overrides.get(`${ev.kind}_${i}`) ?? t.score), 0)
    return (earnedNow / ev.possible) * 100
  }

  const displayScore = calcOpen
    ? subject.evaluations.reduce((sum, ev) => sum + (ev.weight / totalWeight) * pctOf(ev), 0)
    : subject.score
  const color = colorForPercent(hasData ? displayScore : null)

  return (
    <div className="gr-detail-inner">
      <div className="gr-summary-card">
        {hasEvals && (
          <button
            type="button"
            className="gr-calc-btn"
            style={{ background: calcOpen ? 'rgba(212,175,90,0.2)' : 'var(--bg-sidebar)' }}
            onClick={() => setCalcOpen((v) => !v)}
            aria-label="Калькулятор «что если»"
          >
            🤔
          </button>
        )}
        {hasData ? (
          <>
            <div className="gr-summary-row">
              <span className="gr-summary-percent" style={{ color }}>
                {fmtPct(displayScore, 2)}
              </span>
              <span
                className="gr-summary-mark"
                style={{
                  background: subject.mark ? color : '#1c1c1c',
                  color: subject.mark ? textOnGradeColor(color) : 'var(--text-tertiary)',
                }}
              >
                {subject.mark || '—'}
              </span>
            </div>
            <div className="gr-bar gr-bar-big">
              <div className="gr-bar-fill" style={{ width: `${Math.min(100, Math.max(0, displayScore))}%`, background: color }} />
            </div>
          </>
        ) : (
          <div className="gr-summary-empty">Оценки за эту четверть ещё не выставлены</div>
        )}
      </div>

      {loading ? (
        <div className="gr-skeleton-list">
          <div className="gr-skeleton" />
          <div className="gr-skeleton" />
        </div>
      ) : hasEvals ? (
        <div className="gr-eval-list">
          {subject.evaluations.map((ev) => (
            <div className="gr-eval-card" key={ev.kind}>
              <div className="gr-eval-head">
                <span className="gr-eval-kind">{ev.kind}</span>
                <span className="gr-eval-weight">Вес {fmtNum(ev.weight)}%</span>
              </div>
              <EvaluationTopics
                ev={ev}
                calcOpen={calcOpen}
                overrides={overrides}
                onOverride={(key, value) => setOverrides((m) => new Map(m).set(key, value))}
              />
            </div>
          ))}

          <WeakTopicsCard evaluations={subject.evaluations} />

          <div className="gr-ask-card">
            <div className="gr-ask-title">Сколько нужно, чтобы получить…</div>
            <div className="gr-ask-buttons">
              {[5, 4, 3].map((m) => (
                <button
                  type="button"
                  className={`gr-ask-btn${targetMark === m ? ' is-active' : ''}`}
                  key={m}
                  onClick={() => setTargetMark((prev) => (prev === m ? null : m))}
                >
                  До {m}
                </button>
              ))}
            </div>
            {targetMark && (
              <div className="gr-ask-result">
                {(() => {
                  // СОЧ — всегда последний по времени вид оценивания в четверти
                  // (все СОР к этому моменту уже прошли и не поменяются), так
                  // что считаем именно под него, держа СОР как есть — не
                  // предлагаем гипотетически "пересдать" уже прошедший СОР.
                  const soch = subject.evaluations.find((ev) => ev.kind === 'СОЧ')
                  if (!soch) return <div className="gr-ask-result-empty">СОЧ ещё не запланирован в этой четверти</div>

                  const r = requiredScoreForTarget(subject.evaluations, 'СОЧ', MARK_THRESHOLDS[targetMark])
                  if (!r) return <div className="gr-ask-result-empty">У СОЧ пока нет веса в этой четверти</div>

                  if (r.alreadyDecided) {
                    return (
                      <div className="gr-ask-result-empty">
                        {r.neededPercentOfKind < 0
                          ? 'Уже обеспечено результатами СОР, даже с 0 за СОЧ'
                          : 'Недостижимо — не хватит, даже если набрать 100% за СОЧ'}
                      </div>
                    )
                  }

                  // Баллы за реальные задания целые — округляем вверх (ровно
                  // расчётного дробного балла недостаточно, "34.5 из 50" не
                  // сдать физически), и пересчитываем процент уже от целого
                  // числа баллов, чтобы два числа рядом не противоречили
                  // друг другу.
                  const neededPoints = Math.ceil((r.neededPercentOfKind / 100) * soch.possible)
                  const neededPercent = (neededPoints / soch.possible) * 100
                  return (
                    <div className="gr-ask-result-row">
                      <span className="gr-ask-result-kind">Нужно за СОЧ</span>
                      <span className="gr-ask-result-value">
                        {fmtNum(neededPoints)} / {fmtNum(soch.possible)} ({fmtPct(neededPercent, 1)})
                      </span>
                    </div>
                  )
                })()}
              </div>
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
