/**
 * i18n setup.
 *
 * The backend uses Django language codes (`zh-hant`, `zh-hans`); i18next and
 * `Intl` prefer BCP-47 (`zh-Hant`). Everything is normalised here so the rest
 * of the app never has to think about which spelling it is holding.
 */

import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'

import { LANGUAGE_KEY } from '@/lib/api'
import en from './locales/en'
import zhHant from './locales/zh-Hant'
import zhHans from './locales/zh-Hans'

export const SUPPORTED_LANGUAGES = ['en', 'zh-Hant', 'zh-Hans'] as const
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number]

export const LANGUAGE_LABELS: Record<SupportedLanguage, string> = {
  en: 'English',
  'zh-Hant': '繁體中文',
  'zh-Hans': '简体中文',
}

/** Accepts any casing or the Django spelling and returns a canonical tag. */
export function normalizeLanguage(value: string | null | undefined): SupportedLanguage {
  if (!value) return 'en'
  const lower = value.toLowerCase().replace('_', '-')
  if (lower.startsWith('zh')) {
    if (lower.includes('hans') || lower.includes('cn') || lower.includes('sg')) {
      return 'zh-Hans'
    }
    return 'zh-Hant'
  }
  return 'en'
}

/** The spelling the Django API expects in user preferences. */
export function toApiLanguage(value: SupportedLanguage): string {
  return value.toLowerCase()
}

function detectInitialLanguage(): SupportedLanguage {
  const stored = localStorage.getItem(LANGUAGE_KEY)
  if (stored) return normalizeLanguage(stored)
  for (const candidate of navigator.languages ?? [navigator.language]) {
    const lower = candidate.toLowerCase()
    if (lower.startsWith('zh') || lower.startsWith('en')) return normalizeLanguage(candidate)
  }
  return 'en'
}

const initial = detectInitialLanguage()

void i18next.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    'zh-Hant': { translation: zhHant },
    'zh-Hans': { translation: zhHans },
  },
  lng: initial,
  fallbackLng: 'en',
  supportedLngs: SUPPORTED_LANGUAGES as unknown as string[],
  interpolation: { escapeValue: false },
  returnNull: false,
})

localStorage.setItem(LANGUAGE_KEY, toApiLanguage(initial))
document.documentElement.lang = initial

export function applyLanguage(language: SupportedLanguage): void {
  void i18next.changeLanguage(language)
  localStorage.setItem(LANGUAGE_KEY, toApiLanguage(language))
  document.documentElement.lang = language
}

export function currentLanguage(): SupportedLanguage {
  return normalizeLanguage(i18next.language)
}

export default i18next
