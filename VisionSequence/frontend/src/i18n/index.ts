/**
 * i18n 初始化。zh-Hant 為預設且為 fallback：en 只翻了一部分，缺的 key 退回繁中，
 * 而不是顯示 key 字串。
 */
import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'

import { LANGUAGE_KEY } from '@/lib/api'
import en from './locales/en'
import zhHant from './locales/zh-Hant'

export type Language = 'zh-Hant' | 'en'

export function storedLanguage(): Language {
  try {
    const value = localStorage.getItem(LANGUAGE_KEY)
    return value === 'en' ? 'en' : 'zh-Hant'
  } catch {
    return 'zh-Hant'
  }
}

export function setLanguage(language: Language) {
  try {
    localStorage.setItem(LANGUAGE_KEY, language)
  } catch {
    /* 私密模式 */
  }
  void i18next.changeLanguage(language)
  document.documentElement.lang = language
}

void i18next.use(initReactI18next).init({
  resources: {
    'zh-Hant': { translation: zhHant },
    en: { translation: en },
  },
  lng: storedLanguage(),
  fallbackLng: 'zh-Hant',
  interpolation: { escapeValue: false },
  returnNull: false,
})

export default i18next
