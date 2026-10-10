import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In dev, the dashboard runs on :5173 and forwards API + websocket calls to the backend on :8000.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': 'http://localhost:8000',
      '/ws': { target: 'ws://localhost:8000', ws: true },
    },
  },
})
