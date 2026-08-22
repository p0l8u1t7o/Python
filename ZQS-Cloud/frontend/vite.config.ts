import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    // Bind explicitly: Vite's default `localhost` resolves to ::1 first on
    // Windows and then listens on IPv6 only, so http://127.0.0.1:5173 - which
    // is what tooling and scripts reach for - refuses the connection.
    // Set VITE_DEV_HOST=0.0.0.0 (or pass --host) to expose the dev server to
    // other devices on the LAN, e.g. a phone on the same Wi-Fi. The /api proxy
    // below still targets 127.0.0.1, so only this port has to be reachable.
    host: process.env.VITE_DEV_HOST ?? '127.0.0.1',
    port: 5173,
    strictPort: true,
    // Proxy keeps the browser on one origin in development, so cookies and
    // CORS behave the same as they will behind a reverse proxy in production.
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure(proxy) {
          // The workflow run stream is a long-lived SSE response through this
          // proxy. A browser tab closing mid-stream surfaces as ECONNRESET on
          // the proxied socket, and an unhandled 'error' there takes the whole
          // dev server down - which looked like Vite randomly dying during
          // e2e runs. Answer cleanly and carry on.
          proxy.on('error', (_error, _request, response) => {
            const res = response as { headersSent?: boolean; writeHead?: (code: number) => void; end?: () => void }
            try {
              if (res && !res.headersSent && typeof res.writeHead === 'function') {
                res.writeHead(502)
                res.end?.()
              }
            } catch {
              // The socket is already gone; nothing to answer.
            }
          })
        },
      },
    },
    watch: {
      // Test artefacts (screenshots, traces) are written under the project
      // root during e2e runs; watching them is churn the dev server does not
      // need.
      ignored: ['**/e2e-results/**', '**/test-results/**', '**/dist/**'],
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        // Charts and the map are heavy and not needed on the login screen.
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          charts: ['recharts'],
          map: ['leaflet', 'react-leaflet'],
        },
      },
    },
  },
})
