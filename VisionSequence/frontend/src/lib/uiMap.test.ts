/** 介面地圖：App.tsx 的每條路由都有、每個 i18n key 三語系都解得到、後端的 ui_map.json 與地圖一致。 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import en from '@/i18n/locales/en'
import zhHans from '@/i18n/locales/zh-Hans'
import zhHant from '@/i18n/locales/zh-Hant'
import { buildUiMap, REDIRECT_ROUTES, UI_PAGES } from '@/lib/uiMap'

const dicts: Record<string, unknown> = { en, 'zh-Hant': zhHant, 'zh-Hans': zhHans }
const get = (obj: unknown, key: string): unknown => key.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined), obj)
const t = (lang: string, key: string): string => {
  const v = get(dicts[lang], key)
  if (typeof v !== 'string') throw new Error(`missing i18n key ${key} (${lang})`)
  return v
}
const helpPages = (lang: string) => get(dicts[lang], 'help.content.pages') as [string, string, string, string][]
const ROOT = path.resolve(__dirname, '..', '..')
describe('ui map', () => {
  it('covers every route in App.tsx', () => {
    const src = readFileSync(path.join(ROOT, 'src', 'App.tsx'), 'utf8')
    const routes = new Set(UI_PAGES.map((p) => p.route))
    const missing: string[] = []
    for (const m of src.matchAll(/path: '([^']*)'/g)) {
      const piece = m[1]
      const candidates = piece.startsWith('/') ? [piece] : [`/${piece}`, `/integration/${piece}`]
      if (candidates.some((c) => routes.has(c) || REDIRECT_ROUTES.includes(c))) continue
      missing.push(piece)
    }
    expect(missing, `routes missing from uiMap.ts: ${missing.join(', ')}`).toEqual([])
  })

  it('resolves every key in all three languages and matches the generated JSON', () => {
    const map = buildUiMap(Object.keys(dicts), t, helpPages)
    expect(map.pages.length).toBe(UI_PAGES.length)
    for (const p of map.pages) {
      expect(p.names.en, p.id).toBeTruthy()
      expect(p.summary['zh-Hant'], p.id).toBeTruthy()
    }
    const generated = readFileSync(path.join(ROOT, '..', 'apps', 'vision', 'agent', 'ui_map.json'), 'utf8')
    expect(JSON.parse(generated), 'run "node scripts/ui_map.mjs" in frontend/').toEqual(map)
  })
})
