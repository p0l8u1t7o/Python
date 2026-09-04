/**
 * i18n 初始化。**英文是預設語言，也是 fallback**：產品以英文為主，中文是翻譯。
 * 三個語系的 key 由 `src/test/i18n.test.ts` 把關對齊，所以任何語系缺鍵都會在測試被擋下，
 * 不會在畫面上露出原始 key。
 */
import i18next from 'i18next'
import { initReactI18next } from 'react-i18next'

import { LANGUAGE_KEY } from '@/lib/api'
import en from './locales/en'
import zhHans from './locales/zh-Hans'
import zhHant from './locales/zh-Hant'

export type Language = 'zh-Hant' | 'zh-Hans' | 'en'

export function storedLanguage(): Language {
  try {
    const value = localStorage.getItem(LANGUAGE_KEY)
    if (value === 'en' || value === 'zh-Hans' || value === 'zh-Hant') return value
    // 沒選過語言時跟著瀏覽器：中文的使用者直接看到中文，其餘一律英文。
    const browser = (navigator.language || '').toLowerCase()
    if (browser.startsWith('zh')) return browser.includes('cn') || browser.includes('hans') ? 'zh-Hans' : 'zh-Hant'
    return 'en'
  } catch {
    return 'en'
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
    'zh-Hans': { translation: zhHans },
    en: { translation: en },
  },
  lng: storedLanguage(),
  fallbackLng: 'en',
  interpolation: { escapeValue: false },
  returnNull: false,
})

export default i18next
