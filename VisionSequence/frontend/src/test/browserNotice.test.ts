/** index.html：語言屬性預設英文並在開機腳本套用本機語言；舊瀏覽器有純 HTML 提示；build target 與 Tailwind v4 底線一致。 */
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const ROOT = path.resolve(__dirname, '..', '..')

describe('index.html and build floor', () => {
  it('declares lang=en, applies the stored language before paint and shows a notice on old browsers', () => {
    const html = readFileSync(path.join(ROOT, 'index.html'), 'utf8')
    expect(html).toContain('<html lang="en">')
    expect(html).toContain("localStorage.getItem('vs.language')")
    expect(html).toContain('id="browser-notice"')
    expect(html).toContain('color-mix(in srgb, red, blue)')
    expect(html).toContain('Chrome or Edge 111+')
    // 提示腳本不是 module：舊瀏覽器才跑得到
    const notice = html.slice(html.indexOf('id="browser-notice"'))
    expect(notice).toMatch(/<script>\s*try/)
  })

  it('pins the build target to the Tailwind v4 browser floor', () => {
    const vite = readFileSync(path.join(ROOT, 'vite.config.ts'), 'utf8')
    expect(vite).toContain("'chrome111'")
    expect(vite).toContain("'firefox128'")
    const pkg = JSON.parse(readFileSync(path.join(ROOT, 'package.json'), 'utf8')) as { browserslist: string[] }
    expect(pkg.browserslist).toContain('chrome >= 111')
  })
})
