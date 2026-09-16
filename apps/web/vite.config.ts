import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// В деве фронт (5173) и бэк (8000, apps/api/main.py) — разные порты, а
// значит разные origin для fetch. Проксируем /auth и /api на бэкенд, чтобы
// браузер видел один и тот же origin: куку сессии тогда не разъедает CORS,
// и все fetch('/auth/...') в коде остаются такими же относительными путями,
// как в старом костыльном apps/api/static/index.html.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/auth': 'http://localhost:8000',
      '/api': 'http://localhost:8000',
    },
  },
})
