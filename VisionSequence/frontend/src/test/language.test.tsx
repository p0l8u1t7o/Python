/** 介面語言跟著帳號：/auth/me 的 prefs.language 登入後套用（html lang 也對），切換語言時回寫 /auth/prefs。 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useTranslation } from 'react-i18next'

import { installApiMock, ME } from './apiMock'
import { renderPage } from './render'

installApiMock()

import i18n, { adoptRemoteLanguage } from '@/i18n'
import { api } from '@/lib/api'

function Probe() {
  const { t } = useTranslation()
  return <p data-testid="probe">{t('nav.flows')}</p>
}

describe('language preference', () => {
  afterEach(() => {
    delete (ME.prefs as { language?: string }).language
    adoptRemoteLanguage('en')
  })

  it('adopts the account language after sign-in', async () => {
    ;(ME.prefs as { language?: string }).language = 'zh-Hant'
    renderPage(<Probe />, { route: '/flows' })
    await waitFor(() => expect(i18n.language).toBe('zh-Hant'))
    expect(document.documentElement.lang).toBe('zh-Hant')
    expect(screen.getByTestId('probe').textContent).toBe('流程')
  })

  it('writes the choice back to the account from the Settings page', async () => {
    vi.mocked(api.patch).mockClear()
    const { SettingsPage } = await import('@/pages/SettingsPage')
    renderPage(<SettingsPage />, { route: '/settings?tab=account' })  // 語言與主題在「我的帳號」分頁（D8）
    fireEvent.click(await screen.findByText('简体中文'))
    await waitFor(() => expect(i18n.language).toBe('zh-Hans'))
    expect(localStorage.getItem('vs.language')).toBe('zh-Hans')
    expect(api.patch).toHaveBeenCalledWith('/auth/prefs', { language: 'zh-Hans' })
  })
})
