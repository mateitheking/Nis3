import { useEffect, useState } from 'react'
import { Assistant } from './pages/assistant/Assistant'
import './pages/assistant/assistant.css'
import { Files } from './pages/files/Files'
import './pages/files/files.css'
import { Grades } from './pages/grades/Grades'
import './pages/grades/grades.css'
import { Home } from './pages/home/Home'
import './pages/home/home.css'
import { Login } from './pages/login/Login'
import { Notifications } from './pages/notifications/Notifications'
import './pages/notifications/notifications.css'
import { Register } from './pages/register/Register'
import { Schedule } from './pages/schedule/Schedule'
import './pages/schedule/schedule.css'
import './ui/authForm.css'
import { StubNotice } from './ui/StubNotice'

type Screen =
  | 'register' | 'login' | 'home' | 'schedule' | 'grades' | 'files' | 'notifications' | 'assistant' | 'checking'

const REAL_SCREENS: Record<string, Screen> = {
  Главная: 'home',
  Расписание: 'schedule',
  Оценки: 'grades',
  Файлы: 'files',
  Уведомления: 'notifications',
  NisAI: 'assistant',
}

export default function App() {
  const [screen, setScreen] = useState<Screen>('checking')
  const [stub, setStub] = useState<string | null>(null)

  // При загрузке страницы — если кука сессии ещё жива (см. main.py::/api/me),
  // сразу открываем Главную, а не заставляем логиниться заново на каждое
  // обновление страницы. Ровно то, ради чего вся эта сессия и затевалась.
  useEffect(() => {
    fetch('/api/me', { credentials: 'same-origin' })
      .then((res) => setScreen(res.ok ? 'home' : 'login'))
      .catch(() => setScreen('login'))
  }, [])

  // Единая точка навигации для всех собранных экранов: клик по пункту меню
  // с любого экрана (сайдбар, нижняя навигация, карточка) идёт сюда —
  // известные пункты меняют экран по-настоящему, остальные (пока только
  // NisAI — не подключён к бэкенду) получают честную заглушку.
  function navigate(key: string) {
    const real = REAL_SCREENS[key]
    if (real) setScreen(real)
    else setStub(key)
  }

  if (screen === 'checking') return null

  return (
    <>
      {screen === 'register' && (
        <Register onGoLogin={() => setScreen('login')} onGoHome={() => setScreen('home')} />
      )}
      {screen === 'login' && (
        <Login onGoRegister={() => setScreen('register')} onGoHome={() => setScreen('home')} />
      )}
      {screen === 'home' && <Home onNavigate={navigate} onLoggedOut={() => setScreen('login')} />}
      {screen === 'schedule' && <Schedule onNavigate={navigate} onLoggedOut={() => setScreen('login')} />}
      {screen === 'grades' && <Grades onNavigate={navigate} onLoggedOut={() => setScreen('login')} />}
      {screen === 'files' && <Files onNavigate={navigate} onLoggedOut={() => setScreen('login')} />}
      {screen === 'notifications' && (
        <Notifications onNavigate={navigate} onLoggedOut={() => setScreen('login')} />
      )}
      {screen === 'assistant' && (
        <Assistant onNavigate={navigate} onLoggedOut={() => setScreen('login')} />
      )}
      {stub && <StubNotice screen={stub} onClose={() => setStub(null)} />}
    </>
  )
}
