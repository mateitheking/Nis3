/** Экраны, на которые пока некуда вести (см. design_handoff_navigation/
 * README.md — из всего списка спроектированы только Вход/Главная/
 * Расписание, и то отдельной задачей). Вместо мёртвой кнопки без обратной
 * связи — честная заглушка с названием экрана. */
export function StubNotice({ screen, onClose }: { screen: string; onClose: () => void }) {
  return (
    <div
      role="status"
      style={{
        position: 'fixed',
        left: '50%',
        bottom: 24,
        transform: 'translateX(-50%)',
        background: '#141414',
        border: '1px solid rgba(255,255,255,0.12)',
        borderRadius: 12,
        padding: '12px 16px',
        color: '#f5f5f5',
        fontSize: 13.5,
        fontFamily: 'Inter, system-ui, sans-serif',
        boxShadow: '0 12px 30px rgba(0,0,0,0.5)',
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        zIndex: 100,
      }}
    >
      Экран «{screen}» ещё не собран
      <button
        type="button"
        onClick={onClose}
        style={{
          background: 'none',
          border: 'none',
          color: '#8a8a8a',
          cursor: 'pointer',
          fontSize: 13.5,
          fontFamily: 'inherit',
        }}
      >
        Ок
      </button>
    </div>
  )
}
