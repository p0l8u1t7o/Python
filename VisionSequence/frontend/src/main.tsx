import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import '@/i18n'
import '@/index.css'
import { App } from '@/App'
import { ThemeProvider } from '@/providers/ThemeProvider'
import { ToastProvider } from '@/providers/ToastProvider'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      // 單機系統、視窗切回來不需要重抓；SSE 負責即時。
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <ToastProvider>
          <App />
        </ToastProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </StrictMode>,
)
