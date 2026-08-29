/**
 * 把 full-results.json 的結果標回 CHECKLIST.md：
 *   - `ID` 文字  →  - ✅ `ID` 文字 / - ❌ `ID` 文字 — 原因 / - ⏭ `ID` 文字 — 理由
 *   node frontend/e2e/full-mark.mjs
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const dir = path.dirname(fileURLToPath(import.meta.url))
const md = path.join(dir, 'CHECKLIST.md')
const json = path.join(dir, 'full-results.json')
const { results } = JSON.parse(fs.readFileSync(json, 'utf8'))
const raw = fs.readFileSync(md, 'utf8')
const eol = raw.includes('\r\n') ? '\r\n' : '\n'
const lines = raw.split(eol)
let pass = 0
let fail = 0
let skip = 0
let untested = 0
const out = lines.map((line) => {
  const m = /^- (?:[✅❌⏭] )?`([A-Z]{1,2}\d{2}[a-z]?)` (.*?)(?: — .*)?$/.exec(line)
  if (!m) return line
  const [, id, text] = m
  const r = results[id]
  if (!r) {
    untested += 1
    return `- \`${id}\` ${text}`
  }
  if (r.ok === true) {
    pass += 1
    return `- ✅ \`${id}\` ${text}`
  }
  if (r.ok === null) {
    skip += 1
    return `- ⏭ \`${id}\` ${text} — ${r.note}`
  }
  fail += 1
  return `- ❌ \`${id}\` ${text} — ${r.note}`
})
fs.writeFileSync(md, out.join(eol))
console.log(`✅ ${pass}  ❌ ${fail}  ⏭ ${skip}  未回報 ${untested}`)
