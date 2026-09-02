/** 三語系 key 對齊與文案規範：zh-Hans 必須與 zh-Hant 完全同構；所有語系不得留口語詞。 */
import { describe, expect, it } from 'vitest'

import en from '@/i18n/locales/en'
import zhHans from '@/i18n/locales/zh-Hans'
import zhHant from '@/i18n/locales/zh-Hant'

function flatten(obj: Record<string, unknown>, prefix = ''): Map<string, string> {
  const out = new Map<string, string>()
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix ? `${prefix}.${k}` : k
    if (v && typeof v === 'object') for (const [ck, cv] of flatten(v as Record<string, unknown>, key)) out.set(ck, cv)
    else out.set(key, String(v))
  }
  return out
}

const hant = flatten(zhHant)
const hans = flatten(zhHans)
const eng = flatten(en)

describe('i18n locales', () => {
  it('zh-Hans has exactly the same keys as zh-Hant', () => {
    const missing = [...hant.keys()].filter((k) => !hans.has(k))
    const extra = [...hans.keys()].filter((k) => !hant.has(k))
    expect(missing, `missing in zh-Hans: ${missing.slice(0, 20).join(', ')}`).toEqual([])
    expect(extra, `extra in zh-Hans: ${extra.slice(0, 20).join(', ')}`).toEqual([])
  })

  it('en keys all exist in zh-Hant (en is a partial overlay, fallback is zh-Hant)', () => {
    const extra = [...eng.keys()].filter((k) => !hant.has(k))
    expect(extra, `en has keys unknown to zh-Hant: ${extra.slice(0, 20).join(', ')}`).toEqual([])
  })

  it('interpolation placeholders match between zh-Hant and zh-Hans', () => {
    const bad: string[] = []
    for (const [k, v] of hant) {
      const a = [...v.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort().join(',')
      const b = [...(hans.get(k) ?? '').matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort().join(',')
      if (a !== b) bad.push(`${k}: ${a} vs ${b}`)
    }
    expect(bad).toEqual([])
  })

  it('zh-Hant contains no colloquial wording (商用文案規範)', () => {
    const banned = ['點一下', '試跑', '還沒有', '這個', '看看', '試試', '太敏感', '漏抓', '幫我', '搞', '丟掉', '一堆']
    const hits: string[] = []
    for (const [k, v] of hant) for (const w of banned) if (v.includes(w)) hits.push(`${k} ⟶ ${w}`)
    expect(hits).toEqual([])
  })

  it('no empty strings', () => {
    const empty = [...hant].filter(([, v]) => v.trim() === '').map(([k]) => k)
    expect(empty).toEqual([])
  })
})
