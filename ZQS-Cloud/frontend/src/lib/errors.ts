/**
 * Turns an API failure into a sentence the user can act on.
 *
 * The backend sends a stable `code` precisely so the console can translate it;
 * the server's English `message` is only the fallback when a code has no
 * translation yet, which is better than showing the user nothing.
 */

import i18next from 'i18next'

import { ApiError } from './api'

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const key = `errors.${error.code}`
    const translated = i18next.t(key)
    if (translated !== key) return translated

    if (error.code === 'validation_error') {
      const detail = firstValidationDetail(error.details)
      if (detail) return detail
    }
    return error.message || i18next.t('errors.generic')
  }

  if (error instanceof TypeError) {
    // fetch() rejects with a TypeError when the host is unreachable.
    return i18next.t('errors.network')
  }
  if (error instanceof Error && error.message) return error.message
  return i18next.t('errors.generic')
}

function firstValidationDetail(details: unknown): string | null {
  if (!Array.isArray(details) || details.length === 0) return null
  const first = details[0] as { field?: string; message?: string }
  if (!first?.message) return null
  return first.field ? `${first.field}: ${first.message}` : first.message
}

/** Field-level messages, for highlighting inputs in a form. */
export function fieldErrors(error: unknown): Record<string, string> {
  if (!(error instanceof ApiError) || !Array.isArray(error.details)) return {}
  const result: Record<string, string> = {}
  for (const item of error.details as { field?: string; message?: string }[]) {
    if (item?.field && item.message && !result[item.field]) {
      result[item.field] = item.message
    }
  }
  return result
}

export function isPermissionError(error: unknown): boolean {
  return error instanceof ApiError && error.status === 403
}

export function isNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}
