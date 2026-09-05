/** 助手視窗三語系：提示卡、動作晶片、已查詢、評分、記憶面板、截圖晶片與各按鈕提示都來自字典——沒有原始 key、中文介面沒有英文殘留。 */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { afterAll, beforeEach, describe, expect, it, vi } from 'vitest'

import { installApiMock } from './apiMock'
import { renderPage } from './render'

installApiMock()
vi.mock('@/lib/screenshot', () => ({ captureScreenshot: vi.fn(async () => 'data:image/jpeg;base64,QUJD'), base64Of: (s: string) => s.split(',')[1] ?? s }))

import { AssistantDock } from '@/components/assistant/AssistantDock'
import i18n from '@/i18n'
import { clearActivity, logActivity, setShareEnabled } from '@/lib/activity'
import { api } from '@/lib/api'
import { setAssistantContext } from '@/lib/assistantContext'
import { resetHints } from '@/lib/hints'

const EXPECT: Record<string, string[]> = {
  en: ['Hint', 'Ask the assistant', 'Checked: list_flows, list_plugins (not permitted)', 'Remembered facts', 'Screenshot attached to the next question', 'Helpful', 'Remember'],
  'zh-Hant': ['提示', '詢問助手', '已查詢: list_flows, list_plugins (無權限)', '記住的事實', '截圖已附在下一則提問', '有幫助', '記住'],
  'zh-Hans': ['提示', '询问助手', '已查询: list_flows, list_plugins (无权限)', '记住的事实', '截图已附在下一条提问', '有帮助', '记住'],
}
//: 顯示出原始 key 的樣子（assistant.memory.open…）
const RAW_KEY = /\b(assistant|common|agent|batchPage|editor|nav)\.[a-zA-Z]+(\.[a-zA-Z]+)+\b/

function visibleText(): string {
  const dock = screen.getByTestId('assistant-dock')
  const attrs = [...dock.querySelectorAll('[title], [aria-label], [placeholder]')].flatMap((el) => [el.getAttribute('title'), el.getAttribute('aria-label'), el.getAttribute('placeholder')])
  return [dock.textContent ?? '', ...attrs].filter(Boolean).join('\n')
}

describe.each(Object.keys(EXPECT))('assistant dock in %s', (lang) => {
  beforeEach(async () => {
    localStorage.clear()
    sessionStorage.clear()
    clearActivity()
    resetHints()
    setShareEnabled(true)
    setAssistantContext(null)
    vi.mocked(api.post).mockClear()
    await i18n.changeLanguage(lang)
  })
  afterAll(async () => { await i18n.changeLanguage('en') })

  it('shows every piece of the assistant from the dictionary', async () => {
    const original = vi.mocked(api.get).getMockImplementation()!
    vi.mocked(api.get).mockImplementation(async (path: string) => (path.startsWith('/vision/agent/info') ? { provider: 'openai', model: 'gpt-4o', llm: true, mode: 'single' } : original(path)))
    try {
      setAssistantContext({ kind: 'flow_editor', flowId: 1, flowName: 'F', focusNode: () => {} })
      vi.mocked(api.post).mockResolvedValueOnce({ kind: 'help', answer: 'ok', provider: 'openai', memory_id: 5,
        sources: [{ title: 'Interface › Source library', page: 'ui', heading: 'Source library', url: '/sources', snippet: '', kind: 'ui' }],
        actions: [{ kind: 'navigate', to: '/sources', label: 'go' }], lookups: [{ name: 'list_flows', args: {} }, { name: 'list_plugins', args: {}, error: 'x' }] })
      renderPage(<AssistantDock />, { route: '/flows/1' })
      fireEvent.click(screen.getByTestId('assistant-toggle'))
      logActivity('error', 'POST /vision/flows/1/run -> 423 engine_locked', 'locked by integrator')
      await waitFor(() => expect(screen.getByTestId('assistant-hint')).toBeTruthy())
      await waitFor(() => expect((screen.getByTestId('assistant-shot') as HTMLButtonElement).disabled).toBe(false))
      fireEvent.click(screen.getByTestId('assistant-shot'))
      await waitFor(() => expect(screen.getByTestId('assistant-shot-chip')).toBeTruthy())
      let all = visibleText()
      const input = screen.getByTestId('assistant-input') as HTMLInputElement
      fireEvent.change(input, { target: { value: 'q' } })
      fireEvent.keyDown(input, { key: 'Enter' })
      await waitFor(() => expect(screen.getByTestId('assistant-rate-up')).toBeTruthy())
      all += '\n' + visibleText()
      fireEvent.click(screen.getByTestId('assistant-memory-toggle'))
      await waitFor(() => expect(screen.getAllByTestId('assistant-memory-fact').length).toBe(1))
      all += '\n' + visibleText()
      expect(all).not.toMatch(RAW_KEY)
      for (const s of EXPECT[lang]) expect(all, `${lang} should show "${s}"`).toContain(s)
      if (lang !== 'en') {
        for (const s of ['Remembered facts', 'Ask the assistant', 'Checked:', 'Helpful', 'Dismiss', 'Screenshot attached']) expect(all, `${lang} leaks English "${s}"`).not.toContain(s)
      }
    } finally {
      vi.mocked(api.get).mockImplementation(original)
    }
  })
})
