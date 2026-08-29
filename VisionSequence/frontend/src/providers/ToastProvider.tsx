/** 右下角提示。停留時間：成功／資訊 2 秒、警告 3.5 秒、錯誤 6 秒；可手動關閉，push 可指定毫秒。 */
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react'
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'

type ToastKind = 'success' | 'error' | 'info' | 'warning'

interface Toast {
  id: number
  kind: ToastKind
  message: string
}

interface ToastContextValue {
  push: (message: string, kind?: ToastKind, durationMs?: number) => void
  success: (message: string) => void
  error: (message: string) => void
  warning: (message: string) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const ICONS: Record<ToastKind, typeof Info> = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
}
const DURATION: Record<ToastKind, number> = { success: 2000, info: 2000, warning: 3500, error: 6000 }
const ACCENT: Record<ToastKind, string> = {
  success: 'text-ok',
  error: 'text-critical',
  warning: 'text-warning',
  info: 'text-info',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([])
  const nextId = useRef(1)

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((toast) => toast.id !== id))
  }, [])

  const push = useCallback(
    (message: string, kind: ToastKind = 'info', durationMs?: number) => {
      const id = nextId.current++
      setToasts((current) => [...current.slice(-4), { id, kind, message }])
      window.setTimeout(() => dismiss(id), durationMs ?? DURATION[kind])
    },
    [dismiss],
  )

  const value = useMemo<ToastContextValue>(
    () => ({
      push,
      success: (m) => push(m, 'success'),
      error: (m) => push(m, 'error'),
      warning: (m) => push(m, 'warning'),
    }),
    [push],
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2" role="status" aria-live="polite">
        {toasts.map((toast) => {
          const Icon = ICONS[toast.kind]
          return (
            <div key={toast.id} className="card flex items-start gap-3 p-3 shadow-lg shadow-black/20">
              <Icon className={`mt-0.5 size-4 shrink-0 ${ACCENT[toast.kind]}`} />
              <p className="flex-1 text-sm leading-snug">{toast.message}</p>
              <button type="button" onClick={() => dismiss(toast.id)} className="text-subtle hover:text-content" aria-label="Dismiss">
                <X className="size-4" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast(): ToastContextValue {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used inside ToastProvider')
  return ctx
}
