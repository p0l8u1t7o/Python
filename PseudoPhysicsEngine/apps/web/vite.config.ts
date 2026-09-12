import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // Three.js is intentionally lazy-loaded as a dedicated viewer chunk.
    chunkSizeWarningLimit: 650,
  },
  server: {
    proxy: {
      '/api': apiProxyTarget,
    },
  },
})
