import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import '@/i18n'
import '@/index.css'
import { App } from '@/App'
import { setStreamClient } from '@/lib/flowStream'
import { ThemeProvider } from '@/providers/ThemeProvider'
import { ToastProvider } from '@/providers/ToastProvider'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      // 多客戶端：即時靠 SSE；只有清單類查詢（流程、容量）自己開 refetchOnWindowFocus，流程詳情不開（編輯器的重載會重設畫布）。
      refetchOnWindowFocus: false,
      staleTime: 10_000,
    },
  },
})
setStreamClient(queryClient)

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
