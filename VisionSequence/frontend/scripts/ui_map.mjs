/**
 * 產生 apps/vision/agent/ui_map.json：把 src/lib/uiMap.ts 的介面地圖用三種語系解析成後端 AI 助手要的 JSON。
 * 用 esbuild 把 uiMap.ts＋三份字典打成一個 CJS 暫存檔再執行（不用另外裝 ts 執行器）。
 *   node scripts/ui_map.mjs          寫檔
 *   node scripts/ui_map.mjs --check  只比對，過期回 1（vitest 也會擋）
 */
import { buildSync } from 'esbuild'
import { createRequire } from 'node:module'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const root = path.resolve(here, '..')
const target = path.resolve(root, '..', 'apps', 'vision', 'agent', 'ui_map.json')
const entry = `
import { buildUiMap } from './src/lib/uiMap'
import en from './src/i18n/locales/en'
import zhHant from './src/i18n/locales/zh-Hant'
import zhHans from './src/i18n/locales/zh-Hans'
const dicts = { en, 'zh-Hant': zhHant, 'zh-Hans': zhHans }
function get(obj, key) {
  return key.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), obj)
}
function t(lang, key) {
  const v = get(dicts[lang], key)
  if (typeof v !== 'string') throw new Error('missing i18n key ' + key + ' (' + lang + ')')
  return v
}
module.exports = buildUiMap(Object.keys(dicts), t, (lang) => get(dicts[lang], 'help.content.pages'))
`

const dir = mkdtempSync(path.join(tmpdir(), 'vs-ui-map-'))
try {
  const entryFile = path.join(root, '.ui_map_entry.ts')
  writeFileSync(entryFile, entry)
  const out = path.join(dir, 'ui_map.cjs')
  try {
    buildSync({ entryPoints: [entryFile], bundle: true, platform: 'node', format: 'cjs', outfile: out, alias: { '@': path.join(root, 'src') }, logLevel: 'silent' })
  } finally {
    rmSync(entryFile, { force: true })
  }
  const map = createRequire(import.meta.url)(out)
  const text = JSON.stringify(map, null, 1) + '\n'
  if (process.argv.includes('--check')) {
    let current = ''
    try { current = readFileSync(target, 'utf8') } catch { /* 沒有檔案就是過期 */ }
    if (current !== text) {
      console.error(`ui_map.json is out of date: run "node scripts/ui_map.mjs" in frontend/`)
      process.exit(1)
    }
    console.log('ui_map.json is up to date')
  } else {
    writeFileSync(target, text)
    console.log(`wrote ${target} (${map.pages.length} pages)`)
  }
} finally {
  rmSync(dir, { recursive: true, force: true })
}
