/** 登入頁：系統尚未有使用者時改成「建立第一個管理員」表單；成功後導回原頁。 */
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation, useNavigate } from 'react-router-dom'
import { LogIn, ShieldPlus } from 'lucide-react'

import { Button, LoadingState, TextInput } from '@/components/ui'
import { errorMessage } from '@/lib/errors'
import { useAuth } from '@/providers/AuthProvider'

export function LoginPage() {
  const { t } = useTranslation()
  const auth = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const from = (location.state as { from?: string } | null)?.from || '/'
  if (auth.loading) return <LoadingState />
  if (auth.authenticated) return <Navigate to={from} replace />

  const setupMode = auth.setupRequired

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    if (!username.trim() || !password) {
      setError(t('auth.required'))
      return
    }
    if (setupMode && password.length < 6) {
      setError(t('auth.weakPassword'))
      return
    }
    setBusy(true)
    setError('')
    try {
      if (setupMode) await auth.setup(username.trim(), password, displayName.trim())
      else await auth.login(username.trim(), password)
      navigate(from, { replace: true })
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex h-screen w-screen items-center justify-center bg-canvas p-4">
      <form onSubmit={(e) => void onSubmit(e)} className="card w-full max-w-sm space-y-4 p-6" data-testid="login-form">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-lg bg-brand text-on-brand">
            <span className="text-sm font-bold">VS</span>
          </div>
          <div>
            <h1 className="text-base font-semibold">{t('app.name')}</h1>
            <p className="text-xs text-muted">{setupMode ? t('auth.setupTitle') : t('auth.loginTitle')}</p>
          </div>
        </div>
        {setupMode ? <p className="rounded-lg bg-brand-soft px-3 py-2 text-xs text-brand">{t('auth.setupHint')}</p> : null}
        <TextInput label={t('auth.username')} autoFocus autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        <TextInput label={t('auth.password')} type="password" autoComplete={setupMode ? 'new-password' : 'current-password'} value={password} onChange={(e) => setPassword(e.target.value)} hint={setupMode ? t('auth.passwordHint') : undefined} />
        {setupMode ? <TextInput label={t('auth.displayName')} value={displayName} onChange={(e) => setDisplayName(e.target.value)} /> : null}
        {error ? <p className="text-xs text-critical" role="alert">{error}</p> : null}
        <Button type="submit" variant="primary" className="w-full" loading={busy} icon={setupMode ? <ShieldPlus size={15} /> : <LogIn size={15} />}>
          {setupMode ? t('auth.setupSubmit') : t('auth.loginSubmit')}
        </Button>
      </form>
    </div>
  )
}
