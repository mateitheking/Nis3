import { useEffect, useState } from 'react'

/**
 * Дизайн Регистрации — два ОТДЕЛЬНЫХ макета (десктоп-карточка по центру и
 * мобильный full-height лист с прилипающей кнопкой снизу), не один и тот же
 * DOM с CSS-адаптацией: на мобильном кнопка отправки физически вынесена из
 * прокручиваемого контента в отдельный sticky-футер, на десктопе она —
 * обычный элемент внутри карточки. Это нельзя честно сделать чистым CSS без
 * дублирования кнопки, поэтому выбираем макет в JS по ширине вьюпорта.
 */
export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches)

  useEffect(() => {
    const mql = window.matchMedia(query)
    const onChange = () => setMatches(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [query])

  return matches
}
