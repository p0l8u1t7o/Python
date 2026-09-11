/**
 * 三語系 key 對齊與文案規範：**英文是正本**，中文兩份必須與它完全同構；中文不得留口語詞。
 * 另外把關「畫面上不得寫死全形標點」——那種字不管切成哪一種語言都會出現。
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
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

  /** 英文的 i18next 複數變體（key_one／key_other）：中文不分單複數，維持 base key 即可（找不到變體會退回 base） */
  const isPluralVariant = (k: string) => /_(one|other)$/.test(k) && eng.has(k.replace(/_(one|other)$/, ''))

  it('en and zh-Hant have exactly the same keys (en is the source of truth)', () => {
    const missing = [...eng.keys()].filter((k) => !hant.has(k) && !isPluralVariant(k))
    const untranslated = [...hant.keys()].filter((k) => !eng.has(k))
    expect(missing, `en has keys unknown to zh-Hant: ${missing.slice(0, 20).join(', ')}`).toEqual([])
    expect(untranslated, `English is the default language, so nothing may be missing from en: ${untranslated.slice(0, 20).join(', ')}`).toEqual([])
  })

  it('placeholders match between en and zh-Hant', () => {
    const bad: string[] = []
    for (const [k, v] of eng) {
      if (isPluralVariant(k)) continue
      const a = [...v.matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort().join(',')
      const b = [...(hant.get(k) ?? '').matchAll(/\{\{(\w+)\}\}/g)].map((m) => m[1]).sort().join(',')
      if (a !== b) bad.push(`${k}: ${a} vs ${b}`)
    }
    expect(bad).toEqual([])
  })

  it('English count strings carry _one/_other plural forms (no "1 pictures")', () => {
    // PM-REVIEW-R2 L-6：帶 {{count}} 且名詞緊接在後的英文字串要有 i18next 複數變體
    const missing = [...eng].filter(([k, v]) => /\{\{count\}\} [a-z]+s/.test(v) && !/_(one|other)$/.test(k) && !eng.has(`${k}_one`)).map(([k]) => k)
    expect(missing).toEqual([])
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

  it('zh-Hans uses mainland terms consistently (PM-REVIEW-R2 L-2)', () => {
    // 同一畫面曾同時出現 影像／图像、范本／模板、批次／批量；統一成大陸慣用詞後由這裡擋住混回去
    const banned = ['影像', '范本', '储存', '拖曳', '批次']
    const hits: string[] = []
    for (const [k, v] of hans) for (const w of banned) if (v.includes(w)) hits.push(`${k} ⟶ ${w}`)
    expect(hits).toEqual([])
  })

  it('no empty strings', () => {
    const empty = [...hant].filter(([, v]) => v.trim() === '').map(([k]) => k)
    expect(empty).toEqual([])
  })
})

/** 語系檔以外的原始碼：全形標點寫在 JSX 或樣板字串裡，英文介面就會看到「Inputs：」。 */
describe('source files', () => {
  const FULLWIDTH = /[：、；（）～　]/
  /** 只掃會進畫面的檔案；語系檔、開發示範頁與測試假資料的中文是資料本身。 */
  const SKIP = ['/i18n/locales/', '/lib/toolLocale.ts', '/components/viewer/ImageViewerDemo.tsx', '/test/', '.test.']

  function walk(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      const path = join(dir, name)
      if (statSync(path).isDirectory()) return walk(path)
      return /\.tsx?$/.test(name) ? [path] : []
    })
  }

  function codeOf(line: string): string {
    // 只看程式碼：行首註解整行跳過，行內註解取 // 之前，JSX 的 {/* … */} 整段挖掉
    const trimmed = line.trimStart()
    if (trimmed.startsWith('//') || trimmed.startsWith('*') || trimmed.startsWith('/*')) return ''
    const without = line.replace(/\{?\/\*[\s\S]*?\*\/\}?/g, '')  // {/* … */} 與行內 /** … */ 都是註解
    const at = without.indexOf('//')
    return at >= 0 ? without.slice(0, at) : without
  }

  it('contains no hard-coded full-width punctuation', () => {
    const hits: string[] = []
    let block = false
    for (const path of walk('src')) {
      const normalised = path.replace(/\\/g, '/')
      if (SKIP.some((s) => normalised.includes(s))) continue
      block = false
      readFileSync(path, 'utf8').split('\n').forEach((line, i) => {
        const trimmed = line.trimStart()
        if (block) {
          if (line.includes('*/')) block = false
          return
        }
        if (trimmed.startsWith('/*') || trimmed.startsWith('{/*')) {
          block = !line.includes('*/')
          return
        }
        if (FULLWIDTH.test(codeOf(line))) hits.push(`${normalised}:${i + 1}`)
      })
    }
    expect(hits, `全形標點會在英文介面露出來，請改半形：\n${hits.join('\n')}`).toEqual([])
  })
})
