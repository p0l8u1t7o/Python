import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Navigate, useLocation } from 'react-router-dom'
import { BatteryCharging, Globe, Monitor, Moon, Sun } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useTheme } from '@/providers/ThemeProvider'
import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES, applyLanguage, currentLanguage } from '@/i18n'
import type { SupportedLanguage } from '@/i18n'
import { errorMessage } from '@/lib/errors'
import type { ThemePreference } from '@/lib/types'
import { Button, SegmentedControl, TextInput } from '@/components/ui'

export function LoginPage() {
  const { t } = useTranslation()
  const { me, signIn, loading, ready } = useAuth()
  const { preference, setPreference } = useTheme()
  const location = useLocation()

  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [language, setLanguage] = useState<SupportedLanguage>(currentLanguage())

  if (ready && me) {
    const from = (location.state as { from?: string } | null)?.from
    return <Navigate to={from ?? '/'} replace />
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      await signIn(email.trim(), password)
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-7 flex flex-col items-center text-center">
          <span
            className="mb-3 grid size-12 place-items-center rounded-2xl bg-brand text-on-brand"
            aria-hidden
          >
            <BatteryCharging className="size-6" />
          </span>
          <h1 className="text-xl font-semibold tracking-tight">{t('auth.title')}</h1>
          <p className="mt-1 text-sm text-muted">{t('auth.subtitle')}</p>
        </div>

        <form onSubmit={onSubmit} className="card space-y-4 p-5">
          <TextInput
            label={t('auth.email')}
            type="email"
            autoComplete="username"
            required
            autoFocus
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
          />
          <TextInput
            label={t('auth.password')}
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />

          {error ? (
            <p
              role="alert"
              className="rounded-lg bg-critical-soft px-3 py-2 text-sm text-critical"
            >
              {error}
            </p>
          ) : null}

          <Button
            type="submit"
            variant="primary"
            loading={loading}
            className="w-full"
            disabled={!email || !password}
          >
            {loading ? t('auth.signingIn') : t('auth.signIn')}
          </Button>
        </form>

        {/* Available before signing in, because someone who cannot read the
            form yet still needs to change the language. */}
        <div className="mt-5 flex flex-wrap items-center justify-center gap-3">
          <SegmentedControl<SupportedLanguage>
            size="sm"
            value={language}
            onChange={(value) => {
              setLanguage(value)
              applyLanguage(value)
            }}
            options={SUPPORTED_LANGUAGES.map((code) => ({
              value: code,
              label: LANGUAGE_LABELS[code],
            }))}
          />
          <SegmentedControl<ThemePreference>
            size="sm"
            value={preference}
            onChange={setPreference}
            options={[
              { value: 'system', label: <Monitor className="size-3.5" />, title: t('theme.system') },
              { value: 'light', label: <Sun className="size-3.5" />, title: t('theme.light') },
              { value: 'dark', label: <Moon className="size-3.5" />, title: t('theme.dark') },
            ]}
          />
        </div>
        <p className="mt-3 flex items-center justify-center gap-1.5 text-xs text-subtle">
          <Globe className="size-3" aria-hidden />
          {t('language.label')} · {t('theme.label')}
        </p>
      </div>
    </div>
  )
}
