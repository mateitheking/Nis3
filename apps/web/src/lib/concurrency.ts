/** Ограничитель параллелизма — не больше `concurrency` вызовов `fn`
 * одновременно, остальные ждут очереди.
 *
 * Причина существования — живой случай 15 сентября 2026: страница
 * Расписания на каждой загрузке била по EduPage 11 параллельными
 * запросами (5 дней расписания + 5 дней замен/консультаций + ближайшие
 * события), и под этой нагрузкой EduPage время от времени отвечал
 * мусором вместо нормального JSON/HTML — библиотека на бэкенде падала
 * (IndexError/JSONDecodeError/ExpiredSessionException), день или карточка
 * становились 500-й ошибкой. Один повтор на бэкенде (см.
 * apps/api/sources/edupage.py::_retry_transient) снял большую часть
 * случаев, но не все — под 11-way нагрузкой иногда мусорил и первый, и
 * повторный запрос. Не слать источнику 11 одновременных запросов с одной
 * сессии — более прямой фикс, чем гадать про повторные попытки. */
export function pLimit(concurrency: number) {
  let active = 0
  const queue: (() => void)[] = []

  function runNext() {
    active--
    const run = queue.shift()
    if (run) run()
  }

  return function limit<T>(fn: () => Promise<T>): Promise<T> {
    return new Promise((resolve, reject) => {
      const run = () => {
        active++
        fn().then(
          (v) => {
            resolve(v)
            runNext()
          },
          (e) => {
            reject(e)
            runNext()
          },
        )
      }
      if (active < concurrency) run()
      else queue.push(run)
    })
  }
}
