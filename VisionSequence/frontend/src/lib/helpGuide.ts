/**
 * 使用者指南（docs/guide/<lang>/<page>.md）的純邏輯：載入、標題與錨點解析、Markdown → 安全 HTML、站內連結改寫、關鍵字搜尋。
 * 正本是 docs/guide/en，zh-Hant／zh-Hans 是譯本；沒有譯本就退回 en（頁面顯示提示）。
 * Markdown 慣例：`## Title {#id}` 帶錨點（前端與後端 help.py 同一套）；截圖是原樣保留的 <figure class="shot"> HTML 區塊。
 */
import DOMPurify from 'dompurify'
import { Marked, type Tokens } from 'marked'

export const GUIDE_PAGES = ['user-guide', 'samples', 'vision-capabilities', 'calibration', 'batch', 'dl', 'agent', 'golden', 'glossary'] as const
export type GuidePage = (typeof GUIDE_PAGES)[number]
export const GUIDE_LANGS = ['en', 'zh-Hant', 'zh-Hans'] as const
export type GuideLang = (typeof GUIDE_LANGS)[number]

export function isGuidePage(value: string | undefined): value is GuidePage {
  return !!value && (GUIDE_PAGES as readonly string[]).includes(value)
}

// 每一頁各自 lazy 一個 chunk；底線開頭的檔案是翻譯用的片段，不列
const sources = import.meta.glob('../../../docs/guide/*/*.md', { query: '?raw', import: 'default' }) as Record<string, () => Promise<string>>

function sourceKey(lang: string, page: string): string | undefined {
  const suffix = `/docs/guide/${lang}/${page}.md`
  return Object.keys(sources).find((k) => k.endsWith(suffix))
}

export function availableLangs(page: GuidePage): GuideLang[] {
  return GUIDE_LANGS.filter((lang) => !!sourceKey(lang, page))
}

export interface LoadedGuide {
  page: GuidePage
  lang: GuideLang
  requested: string
  md: string
  fallback: boolean
}

/** 讀一頁：先找目前語系，沒有就退回 en 並標 fallback。 */
export async function loadGuide(lang: string, page: GuidePage): Promise<LoadedGuide> {
  const wanted = (GUIDE_LANGS as readonly string[]).includes(lang) ? (lang as GuideLang) : 'en'
  const key = sourceKey(wanted, page) ?? sourceKey('en', page)
  if (!key) throw new Error(`guide page missing: ${page}`)
  const actual = key.includes(`/guide/${wanted}/`) ? wanted : 'en'
  const md = await sources[key]()
  return { page, lang: actual, requested: lang, md, fallback: actual !== wanted }
}

export interface Heading {
  level: number
  text: string
  id: string
}

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/<[^>]+>/g, '')
    .replace(/[`*_]/g, '')
    .replace(/[^\p{L}\p{N}]+/gu, '-')
    .replace(/^-+|-+$/g, '')
}

/** `Title {#id}` → { text, id }；沒寫錨點就用 slug。 */
export function splitAnchor(raw: string): { text: string; id: string } {
  const m = /\s*\{#([\w-]+)\}\s*$/.exec(raw)
  if (m) return { text: raw.slice(0, m.index).trim(), id: m[1] }
  return { text: raw.trim(), id: slugify(raw) }
}

function stripInline(text: string): string {
  return text
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/<[^>]+>/g, ' ')
    .replace(/[`*_]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

/** h1～h3（跳過 ``` 圍欄裡的 #）。 */
export function parseHeadings(md: string): Heading[] {
  const out: Heading[] = []
  let fenced = false
  for (const line of md.split(/\r?\n/)) {
    if (/^```/.test(line)) {
      fenced = !fenced
      continue
    }
    if (fenced) continue
    const m = /^(#{1,3})\s+(.+?)\s*$/.exec(line)
    if (!m) continue
    const { text, id } = splitAnchor(m[2])
    out.push({ level: m[1].length, text: stripInline(text), id })
  }
  return out
}

export function pageTitle(md: string): string {
  const h1 = parseHeadings(md).find((h) => h.level === 1)
  return h1?.text ?? ''
}

export interface GuideSection {
  heading: string
  id: string
  level: number
  text: string
}

/** 依 h2／h3 切段（標題前的內文歸到 id 為空的簡介段），內文轉純文字給搜尋用。 */
export function sectionsOf(md: string): GuideSection[] {
  const out: GuideSection[] = []
  let current: GuideSection = { heading: '', id: '', level: 1, text: '' }
  let fenced = false
  for (const line of md.split(/\r?\n/)) {
    if (/^```/.test(line)) {
      fenced = !fenced
      current.text += ' ' + line.replace(/^```\w*/, '')
      continue
    }
    const m = !fenced ? /^(#{2,3})\s+(.+?)\s*$/.exec(line) : null
    if (m) {
      if (current.heading || current.text.trim()) out.push(current)
      const { text, id } = splitAnchor(m[2])
      current = { heading: stripInline(text), id, level: m[1].length, text: '' }
      continue
    }
    if (/^#\s/.test(line)) continue
    current.text += ' ' + stripInline(line.replace(/^\|?-{3,}\|.*$/, '').replace(/\|/g, ' '))
  }
  if (current.heading || current.text.trim()) out.push(current)
  return out.map((s) => ({ ...s, text: s.text.replace(/\s+/g, ' ').trim() }))
}

export interface SearchHit {
  page: GuidePage
  heading: string
  id: string
  snippet: string
}

/** 關鍵字搜尋：拆詞（空白）後每個詞都要出現（不分大小寫），命中處前後各 80 字當摘要；標題命中排前面。 */
export function searchGuide(pages: { page: GuidePage; md: string }[], query: string, limit = 20): SearchHit[] {
  const terms = query
    .toLowerCase()
    .split(/\s+/)
    .map((t) => t.trim())
    .filter(Boolean)
  if (!terms.length) return []
  const hits: (SearchHit & { score: number })[] = []
  for (const { page, md } of pages) {
    for (const section of sectionsOf(md)) {
      const hay = `${section.heading} ${section.text}`
      const low = hay.toLowerCase()
      if (!terms.every((t) => low.includes(t))) continue
      const inHeading = terms.filter((t) => section.heading.toLowerCase().includes(t)).length
      const first = Math.min(...terms.map((t) => low.indexOf(t)).filter((i) => i >= 0))
      const start = Math.max(0, first - 80)
      const snippet = (start > 0 ? '…' : '') + hay.slice(start, first + 80).trim() + (first + 80 < hay.length ? '…' : '')
      hits.push({ page, heading: section.heading, id: section.id, snippet, score: inHeading * 10 + (section.level === 2 ? 1 : 0) })
    }
  }
  hits.sort((a, b) => b.score - a.score)
  return hits.slice(0, limit).map(({ score: _s, ...rest }) => rest)
}

export interface LinkTarget {
  href: string
  /** 應用內路由（/help/<page>#anchor），有值就用 navigate */
  to?: string
  external?: boolean
}

/** 站內連結：`x.md#a` → `/help/x#a`；`#a` → 同頁錨點；`/docs/…`／http(s) 開新分頁；其餘原樣。 */
export function rewriteHref(href: string, currentPage?: string): LinkTarget {
  const m = /^([\w-]+)\.md(#[\w-]+)?$/.exec(href)
  if (m && isGuidePage(m[1])) {
    const to = `/help/${m[1]}${m[2] ?? ''}`
    return { href: to, to }
  }
  if (href.startsWith('#')) {
    const to = currentPage ? `/help/${currentPage}${href}` : href
    return { href, to }
  }
  if (/^(https?:)?\/\//i.test(href) || href.startsWith('/docs/')) return { href, external: true }
  return { href }
}

function escapeAttr(value: string): string {
  return value.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;')
}

function makeMarked(currentPage?: string): Marked {
  return new Marked({
    gfm: true,
    renderer: {
      heading(this: { parser: { parseInline: (tokens: Tokens.Generic[]) => string } }, token: Tokens.Heading) {
        const inner = this.parser.parseInline(token.tokens)
        const { text, id } = splitAnchor(inner)
        return `<h${token.depth} id="${escapeAttr(id)}">${text}</h${token.depth}>\n`
      },
      link(this: { parser: { parseInline: (tokens: Tokens.Generic[]) => string } }, token: Tokens.Link) {
        const text = this.parser.parseInline(token.tokens)
        const target = rewriteHref(token.href, currentPage)
        const attrs = [`href="${escapeAttr(target.href)}"`]
        if (token.title) attrs.push(`title="${escapeAttr(token.title)}"`)
        if (target.external) attrs.push('target="_blank"', 'rel="noreferrer"', 'data-external="1"')
        if (target.to) attrs.push(`data-guide-link="${escapeAttr(target.to)}"`)
        return `<a ${attrs.join(' ')}>${text}</a>`
      },
    },
  })
}

let hooked = false
function ensureHooks(): void {
  if (hooked) return
  hooked = true
  // 圖片只放行平台自己提供的 /docs/img/；連結只放行相對路徑、錨點、/docs/ 與 http(s)
  DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
    if (node.nodeName === 'IMG' && data.attrName === 'src' && !data.attrValue.startsWith('/docs/img/')) data.keepAttr = false
    if (node.nodeName === 'A' && data.attrName === 'href' && !/^(#|\/|https?:\/\/|[\w-]+\.md)/i.test(data.attrValue)) data.keepAttr = false
  })
}

/** Markdown → 已消毒的 HTML；表格外包一層可橫向捲動的容器。 */
export function renderGuide(md: string, currentPage?: string): string {
  ensureHooks()
  const raw = makeMarked(currentPage).parse(md) as string
  const wrapped = raw.replace(/<table>/g, '<div class="table-wrap"><table>').replace(/<\/table>/g, '</table></div>')
  return DOMPurify.sanitize(wrapped, {
    ADD_TAGS: ['figure', 'figcaption'],
    ADD_ATTR: ['data-n', 'data-guide-link', 'data-external', 'target', 'rel'],
    ALLOWED_URI_REGEXP: /^(?:#|\/|https?:\/\/|[\w-]+\.md)/i,
  })
}

export function neighbours(page: GuidePage): { prev?: GuidePage; next?: GuidePage } {
  const i = GUIDE_PAGES.indexOf(page)
  return { prev: i > 0 ? GUIDE_PAGES[i - 1] : undefined, next: i < GUIDE_PAGES.length - 1 ? GUIDE_PAGES[i + 1] : undefined }
}
