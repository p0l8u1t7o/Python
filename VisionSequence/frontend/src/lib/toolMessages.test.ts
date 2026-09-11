import { describe, expect, it } from 'vitest'

import toolMessagesZhHans from '@/i18n/locales/toolMessages.zh-Hans'
import toolMessagesZhHant from '@/i18n/locales/toolMessages.zh-Hant'
import { localiseMessage, nodeMessage } from '@/lib/toolMessages'

describe('tool messages', () => {
  it('fills the Chinese template with the backend-formatted arguments', () => {
    expect(localiseMessage("upstream 'find' skipped", 'engine.upstream_skipped', { node: 'find' }, 'zh-Hant')).toBe('上游步驟「find」已跳過')
    expect(nodeMessage({ message: '3 matches, best 0.975 @ (10.0, 20.0)', message_code: 'template_match.found', message_args: { n: '3', score: '0.975', x: '10.0', y: '20.0' } }, 'zh-Hans'))
      .toBe('3 个匹配，最佳 0.975，位置 (10.0, 20.0)')
  })

  it('falls back to the English sentence', () => {
    expect(localiseMessage('free text', '', {}, 'zh-Hant')).toBe('free text')
    expect(localiseMessage('3 matches', 'template_match.none', { n: '3' }, 'en')).toBe('3 matches')
    expect(localiseMessage('something new', 'no.such.code', {}, 'zh-Hant')).toBe('something new')
    expect(nodeMessage(null, 'zh-Hant')).toBe('')
  })

  it('appends the NG label of a rejecting comparison after the Chinese sentence', () => {
    const code = Object.keys(toolMessagesZhHant).find((key) => !toolMessagesZhHant[key].includes('{'))!
    expect(localiseMessage('anything (Too big)', code, { ng_label: 'Too big' }, 'zh-Hant')).toBe(`${toolMessagesZhHant[code]} (Too big)`)
    expect(localiseMessage('anything (Too big)', code, { ng_label: 'Too big' }, 'en')).toBe('anything (Too big)')
  })

  it('keeps both Chinese dictionaries on the same codes', () => {
    expect(Object.keys(toolMessagesZhHans).sort()).toEqual(Object.keys(toolMessagesZhHant).sort())
  })
})
