import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'node:path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    // Windows 上 localhost 會先解析成 ::1 只聽 IPv6，明確綁 127.0.0.1。
    host: process.env.VITE_DEV_HOST ?? '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000',
        changeOrigin: true,
        configure(proxy) {
          // SSE 經 proxy 時分頁關閉會產生 ECONNRESET，不接住會把 dev server 弄死。
          proxy.on('error', (_error, _request, response) => {
            const res = response as { headersSent?: boolean; writeHead?: (code: number) => void; end?: () => void }
            try {
              if (res && !res.headersSent && typeof res.writeHead === 'function') {
                res.writeHead(502)
                res.end?.()
              }
            } catch {
              /* socket 已消失 */
            }
          })
        },
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    rollupOptions: {
      output: {
        manualChunks: {
          react: ['react', 'react-dom', 'react-router-dom'],
          flow: ['@xyflow/react'],
          charts: ['recharts'],
        },
      },
    },
  },
})
