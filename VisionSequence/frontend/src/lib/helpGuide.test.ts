/**
 * 使用者指南的純邏輯與內容守門：標題錨點、轉譯與消毒、連結改寫、搜尋；
 * 並掃 docs/guide/en/*.md（每頁有 h1、錨點唯一、站內連結指到存在的頁與錨點、圖片只指 /docs/img 且檔案存在），
 * 以及三語系譯本的結構一致（譯本還沒齊時 skip 並印出缺哪些）。
 */
import { existsSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

import { GUIDE_LANGS, GUIDE_PAGES, parseHeadings, renderGuide, rewriteHref, searchGuide, sectionsOf, splitAnchor } from './helpGuide'

const GUIDE_DIR = path.resolve(__dirname, '..', '..', '..', 'docs', 'guide')
const IMG_DIR = path.resolve(__dirname, '..', '..', '..', 'docs', 'img')
const read = (lang: string, page: string) => readFileSync(path.join(GUIDE_DIR, lang, `${page}.md`), 'utf8')

describe('helpGuide parsing', () => {
  it('parses heading anchors and slugs', () => {
    expect(splitAnchor('Getting around {#shell}')).toEqual({ text: 'Getting around', id: 'shell' })
    expect(splitAnchor('Two words')).toEqual({ text: 'Two words', id: 'two-words' })
    const md = '# Title\n\nintro\n\n## A {#a}\n\n```\n## not a heading\n```\n\n### B\n'
    expect(parseHeadings(md)).toEqual([
      { level: 1, text: 'Title', id: 'title' },
      { level: 2, text: 'A', id: 'a' },
      { level: 3, text: 'B', id: 'b' },
    ])
  })

  it('renders sanitized HTML with ids, in-app links and wrapped tables', () => {
    const html = renderGuide('## Batch {#batch}\n\nSee [golden](golden.md#ci) and [ext](https://example.com) and [doc](/docs/modbus.html).\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n<figure class="shot"><img src="/docs/img/x.jpg" alt="x"><figcaption><b>X</b><ol class="callouts"><li data-n="1">one</li></ol></figcaption></figure>\n\n<img src="https://evil/x.png"><script>alert(1)</script>', 'batch')
    expect(html).toContain('<h2 id="batch">Batch</h2>')
    expect(html).toContain('data-guide-link="/help/golden#ci"')
    const ext = /<a [^>]*href="https:\/\/example.com"[^>]*>/.exec(html)?.[0] ?? ''
    expect(ext).toContain('data-external="1"')
    expect(/<a [^>]*href="\/docs\/modbus.html"[^>]*>/.exec(html)?.[0] ?? '').toContain('data-external="1"')
    expect(html).toContain('<div class="table-wrap"><table>')
    expect(html).toContain('data-n="1"')
    expect(html).toContain('src="/docs/img/x.jpg"')
    expect(html).not.toContain('evil')
    expect(html).not.toContain('<script')
  })

  it('rewrites hrefs', () => {
    expect(rewriteHref('batch.md#x')).toEqual({ href: '/help/batch#x', to: '/help/batch#x' })
    expect(rewriteHref('#shell', 'user-guide')).toEqual({ href: '#shell', to: '/help/user-guide#shell' })
    expect(rewriteHref('/docs/automation.html').external).toBe(true)
    expect(rewriteHref('nope.md')).toEqual({ href: 'nope.md' })
  })

  it('searches sections by every term and prefers heading hits', () => {
    const pages = [
      { page: 'batch' as const, md: '# Batch\n\n## Image sets {#sets}\n\nAn image set holds pictures.\n\n## Runs {#runs}\n\nRun the flow over the set of images.' },
      { page: 'golden' as const, md: '# Golden\n\n## Baseline {#base}\n\nGolden set baseline.' },
    ]
    const hits = searchGuide(pages, 'image set')
    expect(hits[0]).toMatchObject({ page: 'batch', id: 'sets' })
    expect(hits.length).toBe(2)
    expect(searchGuide(pages, 'zzz')).toEqual([])
    expect(sectionsOf(pages[0].md).map((s) => s.id)).toEqual(['sets', 'runs'])
  })
})

describe('docs/guide/en content', () => {
  const pages = GUIDE_PAGES.map((page) => ({ page, md: read('en', page) }))
  const anchors = new Map(pages.map(({ page, md }) => [page, new Set(parseHeadings(md).filter((h) => h.level >= 2).map((h) => h.id))]))

  it('every page has one h1 and unique anchors', () => {
    for (const { page, md } of pages) {
      const heads = parseHeadings(md)
      expect(heads.filter((h) => h.level === 1).length, page).toBe(1)
      const ids = heads.filter((h) => h.level >= 2).map((h) => h.id)
      expect(new Set(ids).size, `${page} duplicate anchors`).toBe(ids.length)
    }
  })

  it('internal links point at existing pages and anchors; images exist under docs/img', () => {
    for (const { page, md } of pages) {
      for (const m of md.matchAll(/\]\(([\w-]+)\.md(?:#([\w-]+))?\)/g)) {
        expect((GUIDE_PAGES as readonly string[]).includes(m[1]), `${page}: link to ${m[1]}.md`).toBe(true)
        if (m[2]) expect(anchors.get(m[1] as (typeof GUIDE_PAGES)[number])?.has(m[2]), `${page}: ${m[1]}.md#${m[2]}`).toBe(true)
      }
      for (const m of md.matchAll(/\]\(#([\w-]+)\)/g)) {
        expect(anchors.get(page)?.has(m[1]), `${page}: #${m[1]}`).toBe(true)
      }
      for (const m of md.matchAll(/<img [^>]*src="([^"]+)"/g)) {
        expect(m[1].startsWith('/docs/img/'), `${page}: ${m[1]}`).toBe(true)
        expect(existsSync(path.join(IMG_DIR, m[1].slice('/docs/img/'.length))), `${page}: missing ${m[1]}`).toBe(true)
      }
    }
  })
})

describe('translations', () => {
  for (const lang of GUIDE_LANGS.filter((l) => l !== 'en')) {
    const present = existsSync(path.join(GUIDE_DIR, lang)) ? readdirSync(path.join(GUIDE_DIR, lang)).filter((f) => f.endsWith('.md') && !f.startsWith('_')).map((f) => f.replace(/\.md$/, '')) : []
    const missing = GUIDE_PAGES.filter((p) => !present.includes(p))
    // 譯本還沒齊：先 skip 並印出缺哪些（翻譯批次補齊後這裡自然變成真測）
    const run = missing.length ? it.skip : it
    if (missing.length) console.warn(`[helpGuide] ${lang} translations missing: ${missing.join(', ')}`)
    run(`${lang} pages mirror the English structure`, () => {
      for (const page of GUIDE_PAGES) {
        const en = read('en', page)
        const tr = read(lang, page)
        const enIds = parseHeadings(en).map((h) => h.id)
        const trIds = parseHeadings(tr).map((h) => h.id)
        expect(trIds, `${lang}/${page} anchors`).toEqual(enIds)
        expect((tr.match(/<figure/g) ?? []).length, `${lang}/${page} figures`).toBe((en.match(/<figure/g) ?? []).length)
        expect((tr.match(/\|---/g) ?? []).length, `${lang}/${page} tables`).toBe((en.match(/\|---/g) ?? []).length)
      }
    })
  }
})
