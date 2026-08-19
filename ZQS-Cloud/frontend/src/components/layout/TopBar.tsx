import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Building2, Check, ChevronDown, Globe, LogOut, Menu, Monitor, Moon, Sun, User } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useAuth } from '@/providers/AuthProvider'
import { useTheme } from '@/providers/ThemeProvider'
import { useToast } from '@/providers/ToastProvider'
import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES, currentLanguage, applyLanguage } from '@/i18n'
import type { SupportedLanguage } from '@/i18n'
import type { ThemePreference } from '@/lib/types'
import { errorMessage } from '@/lib/errors'
import { IconButton } from '@/components/ui'

/** Dropdown that closes on outside click and on Escape. */
function Menu2({
  label,
  icon,
  children,
  align = 'right',
}: {
  label: string
  icon: React.ReactNode
  children: (close: () => void) => React.ReactNode
  align?: 'left' | 'right'
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-haspopup="menu"
        className="flex h-8 items-center gap-1.5 rounded-lg px-2 text-sm text-muted
                   transition-colors hover:bg-surface-muted hover:text-content"
      >
        {icon}
        <span className="hidden max-w-32 truncate sm:inline">{label}</span>
        <ChevronDown className="size-3.5 shrink-0" aria-hidden />
      </button>
      {open ? (
        <div
          role="menu"
          className={`card absolute top-full z-50 mt-1 min-w-52 overflow-hidden p-1
                      shadow-xl shadow-black/15 ${align === 'right' ? 'right-0' : 'left-0'}`}
        >
          {children(() => setOpen(false))}
        </div>
      ) : null}
    </div>
  )
}

function MenuItem({
  onClick,
  active,
  children,
}: {
  onClick: () => void
  active?: boolean
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      role="menuitem"
      onClick={onClick}
      className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm
                 text-content transition-colors hover:bg-surface-muted"
    >
      <span className="flex-1 truncate">{children}</span>
      {active ? <Check className="size-3.5 shrink-0 text-brand" aria-hidden /> : null}
    </button>
  )
}

const THEME_ICONS: Record<ThemePreference, typeof Sun> = {
  light: Sun,
  dark: Moon,
  system: Monitor,
}

export function TopBar({ onOpenSidebar }: { onOpenSidebar: () => void }) {
  const { t } = useTranslation()
  const { me, signOut, switchOrganization, savePreferences } = useAuth()
  const { preference, setPreference } = useTheme()
  const toast = useToast()
  const language = currentLanguage()
  const ThemeIcon = THEME_ICONS[preference]

  /** Apply locally first so the UI reacts instantly, then persist. */
  async function chooseTheme(value: ThemePreference) {
    setPreference(value)
    try {
      await savePreferences({ theme: value })
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function chooseLanguage(value: SupportedLanguage) {
    applyLanguage(value)
    try {
      await savePreferences({ language: value })
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <header className="sticky top-0 z-20 flex h-14 items-center gap-2 border-b border-line bg-surface/85 px-3 backdrop-blur sm:px-4">
      <IconButton label="Menu" className="lg:hidden" onClick={onOpenSidebar}>
        <Menu className="size-4" />
      </IconButton>

      <div className="flex-1" />

      {me && me.organizations.length > 1 ? (
        <Menu2 label={me.organization.name} icon={<Building2 className="size-4" />}>
          {(close) =>
            me.organizations.map((membership) => (
              <MenuItem
                key={membership.organization.id}
                active={membership.organization.id === me.organization.id}
                onClick={() => {
                  close()
                  void switchOrganization(membership.organization.slug).catch((error) =>
                    toast.error(errorMessage(error)),
                  )
                }}
              >
                {membership.organization.name}
              </MenuItem>
            ))
          }
        </Menu2>
      ) : me ? (
        <span className="hidden items-center gap-1.5 px-2 text-sm text-muted sm:flex">
          <Building2 className="size-4" aria-hidden />
          <span className="max-w-40 truncate">{me.organization.name}</span>
        </span>
      ) : null}

      <Menu2 label={LANGUAGE_LABELS[language]} icon={<Globe className="size-4" />}>
        {(close) =>
          SUPPORTED_LANGUAGES.map((code) => (
            <MenuItem
              key={code}
              active={code === language}
              onClick={() => {
                close()
                void chooseLanguage(code)
              }}
            >
              {LANGUAGE_LABELS[code]}
            </MenuItem>
          ))
        }
      </Menu2>

      <Menu2 label={t(`theme.${preference}`)} icon={<ThemeIcon className="size-4" />}>
        {(close) =>
          (['system', 'light', 'dark'] as ThemePreference[]).map((value) => (
            <MenuItem
              key={value}
              active={value === preference}
              onClick={() => {
                close()
                void chooseTheme(value)
              }}
            >
              {t(`theme.${value}`)}
            </MenuItem>
          ))
        }
      </Menu2>

      {me ? (
        <Menu2 label={me.user.full_name || me.user.email} icon={<User className="size-4" />}>
          {(close) => (
            <>
              <div className="border-b border-line px-2.5 pb-2 pt-1">
                <p className="truncate text-sm font-medium text-content">
                  {me.user.full_name || me.user.email}
                </p>
                <p className="truncate text-xs text-muted">{me.user.email}</p>
                <p className="mt-1 text-xs text-brand">{t(`role.${me.role}`)}</p>
              </div>
              <Link
                to="/settings"
                onClick={close}
                role="menuitem"
                className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-sm
                           text-content transition-colors hover:bg-surface-muted"
              >
                <User className="size-3.5" aria-hidden />
                {t('settings.title')}
              </Link>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  close()
                  void signOut()
                }}
                className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm
                           text-critical transition-colors hover:bg-surface-muted"
              >
                <LogOut className="size-3.5" aria-hidden />
                {t('auth.signOut')}
              </button>
            </>
          )}
        </Menu2>
      ) : null}
    </header>
  )
}
