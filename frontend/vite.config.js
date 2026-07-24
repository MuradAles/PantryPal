import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The app always calls its own origin and the dev server forwards to the API, so
// no build-time URL is baked in. In compose the backend is a sibling service,
// which is the only reason this is configurable at all.
const target = process.env.VITE_API_TARGET || 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target, changeOrigin: true },
      '/health': { target, changeOrigin: true },
    },
  },
})
