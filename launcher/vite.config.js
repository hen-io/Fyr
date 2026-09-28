import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // In production, nginx proxies /api and /icons to the backend on the
    // same origin - this reproduces that for `npm run dev` so the dashboard
    // actually works locally instead of every fetch 404ing against Vite's
    // own dev server. Assumes the backend is running on 127.0.0.1:8584
    // (the default; override PORT in .env if you've changed it).
    proxy: {
      '/api': 'http://127.0.0.1:8584',
      '/icons': 'http://127.0.0.1:8584',
    },
  },
})
