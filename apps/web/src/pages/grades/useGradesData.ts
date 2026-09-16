import { useCallback, useEffect, useRef, useState } from 'react'
import { useAccountShell } from '../../hooks/useAccountShell'
import { getJsonWithDetail } from '../../lib/apiCache'
import type { GradeSubject, GradesResponse } from '../../types'

function currentAcademicStartYear(): number {
  const now = new Date()
  return now.getMonth() + 1 >= 9 ? now.getFullYear() : now.getFullYear() - 1
}

export function useGradesData() {
  const shell = useAccountShell()
  const [quarter, setQuarterState] = useState(1)
  const [yearOffset, setYearOffset] = useState(0)
  const [subjects, setSubjects] = useState<GradeSubject[] | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [loadingList, setLoadingList] = useState(true)

  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [detail, setDetail] = useState<GradeSubject | null>(null)
  const [loadingDetail, setLoadingDetail] = useState(false)

  const startYear = currentAcademicStartYear() + yearOffset
  const yearLabel = `${startYear}-${startYear + 1}`

  // Счётчик поколений запроса — СУШ отвечает на список предметов не сразу
  // (реальная цепочка из ~7 последовательных запросов к источнику, секунды
  // на ответ, см. docs/sources.md), и если пока первый запрос летит,
  // стартует второй (React StrictMode в dev нарочно вызывает эффект
  // дважды, или пользователь быстро щёлкнул четверть туда-обратно), оба
  // в итоге резолвятся — но не обязательно в порядке старта. Без этой
  // проверки более старый и более медленный ответ мог прилететь ПОСЛЕ
  // нового и переписать состояние устаревшими (в т.ч. пустыми) данными —
  // на экране на миг мелькало честное «Предметов не найдено» перед
  // настоящим списком. Разрешаем применить результат только самому
  // свежему запуску.
  const loadSeq = useRef(0)

  const loadList = useCallback(async () => {
    const seq = ++loadSeq.current
    setLoadingList(true)
    setListError(null)
    setSelectedId(null)
    setDetail(null)
    const res = await getJsonWithDetail<GradesResponse>(
      `/api/grades?quarter=${quarter}&school_year=${encodeURIComponent(yearLabel)}&detailed=false`,
    )
    if (seq !== loadSeq.current) return // устарел — следом уже стартовал новый запрос
    if (res.ok) {
      setSubjects(res.data.subjects)
      setNote(res.data.note)
    } else {
      setSubjects(null)
      setListError(res.detail)
    }
    setLoadingList(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [quarter, yearLabel])

  useEffect(() => {
    loadList()
  }, [loadList])

  const detailSeq = useRef(0)

  async function selectSubject(name: string) {
    const seq = ++detailSeq.current
    setSelectedId(name)
    setDetail(null)
    setLoadingDetail(true)
    // Кэш общий на всё приложение (см. lib/apiCache) — если этот предмет
    // уже открывали в этой же четверти недавно, темы придут мгновенно,
    // без повторного похода в СУШ. Ключ — сам URL, quarter/yearLabel/
    // name в нём уже есть, отдельный кэш здесь не нужен.
    //
    // Адресуемся по имени предмета, не по journal_id: СУШ выдаёт
    // JournalId заново на каждый вызов (сессия внутреннего дневника),
    // так что journal_id из списка не находится в свежем ответе этого
    // эндпоинта — было 404, тихо превращавшееся в «темы не запланированы».
    const res = await getJsonWithDetail<GradeSubject>(
      `/api/grades/subject?name=${encodeURIComponent(name)}&quarter=${quarter}&school_year=${encodeURIComponent(yearLabel)}`,
    )
    if (seq !== detailSeq.current) return // устарел — уже открыли другой предмет
    if (res.ok) setDetail(res.data)
    setLoadingDetail(false)
  }

  function closeDetail() {
    detailSeq.current++ // отменяет ещё летящий запрос темы, если он был
    setSelectedId(null)
    setDetail(null)
  }

  function setQuarter(q: number) {
    setQuarterState(q)
  }

  return {
    ...shell,
    quarter,
    setQuarter,
    yearLabel,
    prevYear: () => setYearOffset((o) => o - 1),
    nextYear: () => setYearOffset((o) => o + 1),
    subjects,
    note,
    listError,
    loadingList,
    selectedId,
    detail,
    loadingDetail,
    selectSubject,
    closeDetail,
  }
}

export type GradesData = ReturnType<typeof useGradesData>
