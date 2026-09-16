import { NavIcon, type NavKey } from './navIcons'

export function BottomNav({
  active,
  onNavigate,
}: {
  active: NavKey
  onNavigate: (key: string) => void
}) {
  const item = (key: NavKey, icon: React.ReactNode) =>
    key === active ? (
      <div className="home-mobile-nav-item is-active" key={key}>
        {icon}
        <span>{key}</span>
      </div>
    ) : (
      <button type="button" className="home-mobile-nav-item" onClick={() => onNavigate(key)} key={key}>
        {icon}
        <span>{key}</span>
      </button>
    )

  return (
    <div className="home-mobile-bottomnav">
      {item('Главная', NavIcon.home)}
      {item('Оценки', NavIcon.grades)}
      {item('Файлы', NavIcon.files)}
      <button
        type="button"
        className="home-mobile-ai-circle"
        onClick={() => onNavigate('NisAI')}
        aria-label="NisAI"
      >
        <span>AI</span>
      </button>
    </div>
  )
}
