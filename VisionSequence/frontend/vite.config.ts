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
      '/docs': { target: process.env.VITE_PROXY_TARGET ?? 'http://127.0.0.1:8000', changeOrigin: true },
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
    // 發行版不出 sourcemap（8 MB、暴露原始碼）；要除錯時 VITE_SOURCEMAP=1 npm run build
    sourcemap: process.env.VITE_SOURCEMAP === '1',
    // 與 Tailwind v4 的 CSS 底線一致（color-mix、@property）：Chrome/Edge 111、Firefox 128、Safari 16.4
    target: ['chrome111', 'edge111', 'firefox128', 'safari16.4'],
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
