/** 把 API 錯誤轉成可以顯示的句子：先找 code 的翻譯，沒有就用伺服器訊息。 */
import i18next from 'i18next'

import { ApiError } from './api'

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const key = `errors.${error.code}`
    const translated = i18next.t(key)
    if (translated !== key && error.code !== 'validation_error') return translated
    return error.message || i18next.t('errors.generic')
  }
  if (error instanceof TypeError) return i18next.t('errors.network')
  if (error instanceof Error && error.message) return error.message
  return i18next.t('errors.generic')
}
