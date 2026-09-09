/**
 * 使用者指南（HelpPage）`/help/:page`：正本是 docs/guide/<lang>/<page>.md（Markdown，三語系），這裡只負責讀、轉譯與導覽。
 * 左側：九頁清單＋本頁章節（捲動高亮）＋工具目錄；上方：關鍵字搜尋（目前語系九頁）；內文：轉譯後的 HTML，
 * 站內連結（x.md#a）在應用內導頁、/docs 與外部連結開新分頁；URL hash 是章節錨點。缺譯本時退回英文並提示。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import { BookOpen, ChevronLeft, ChevronRight, Search, Wrench } from 'lucide-react'

import { ToolsCatalogue } from '@/components/help/ToolsCatalogue'
import { Page } from '@/components/layout/AppShell'
import { Button, PageHeader } from '@/components/ui'
import {
  GUIDE_PAGES,
  type GuidePage,
  type LoadedGuide,
  isGuidePage,
  loadGuide,
  neighbours,
  parseHeadings,
  renderGuide,
  searchGuide,
  type SearchHit,
} from '@/lib/helpGuide'

const TOOLS = 'tools'

export function HelpPage() {
  const { t, i18n } = useTranslation()
  const params = useParams<{ page?: string }>()
  const navigate = useNavigate()
  const location = useLocation()
  // 直接渲染（測試、沒有 <Routes> 包住）時 useParams 是空的：從路徑取
  const pageParam = params.page ?? /^\/help\/([^/#?]+)/.exec(location.pathname)?.[1]
  const page: GuidePage | typeof TOOLS = pageParam === TOOLS ? TOOLS : isGuidePage(pageParam) ? pageParam : 'user-guide'
  const lang = i18n.language
  const [guide, setGuide] = useState<LoadedGuide | null>(null)
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [corpus, setCorpus] = useState<{ page: GuidePage; md: string }[] | null>(null)
  const [active, setActive] = useState('')
  const articleRef = useRef<HTMLDivElement>(null)

  // 讀目前頁（語系變了也重讀）
  useEffect(() => {
    if (page === TOOLS) return
    let alive = true
    setError('')
    loadGuide(lang, page)
      .then((g) => { if (alive) setGuide(g) })
      .catch((e: unknown) => { if (alive) setError(String(e)) })
    return () => { alive = false }
  }, [lang, page])

  // 搜尋：第一次打字時把九頁都讀進來（各自 chunk，只讀一次；換語系重讀）
  useEffect(() => { setCorpus(null) }, [lang])
  useEffect(() => {
    if (!query.trim() || corpus) return
    let alive = true
    Promise.all(GUIDE_PAGES.map((p) => loadGuide(lang, p).then((g) => ({ page: p, md: g.md }))))
      .then((rows) => { if (alive) setCorpus(rows) })
      .catch(() => { /* 缺頁時搜尋只是沒結果 */ })
    return () => { alive = false }
  }, [query, corpus, lang])

  const hits: SearchHit[] = useMemo(() => (corpus && query.trim() ? searchGuide(corpus, query) : []), [corpus, query])
  const headings = useMemo(() => (guide ? parseHeadings(guide.md).filter((h) => h.level >= 2) : []), [guide])
  const html = useMemo(() => (guide ? renderGuide(guide.md, guide.page) : ''), [guide])
  const title = useMemo(() => (guide ? parseHeadings(guide.md).find((h) => h.level === 1)?.text ?? '' : ''), [guide])

  // hash → 捲到章節；內文換頁後回頂
  useEffect(() => {
    if (!html) return
    const id = decodeURIComponent(location.hash.replace(/^#/, ''))
    const el = id ? document.getElementById(id) : null
    if (el) el.scrollIntoView({ block: 'start' })
    else articleRef.current?.closest('[data-testid="help-scroll"]')?.scrollTo?.({ top: 0 })
  }, [html, location.hash])

  // 捲動時高亮目前章節（jsdom 沒有 IntersectionObserver 就略過）
  useEffect(() => {
    if (!html || typeof IntersectionObserver === 'undefined' || !articleRef.current) return
    const targets = headings.map((h) => document.getElementById(h.id)).filter((el): el is HTMLElement => !!el)
    const observer = new IntersectionObserver(
      (entries) => {
        const visible = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)
        if (visible[0]) setActive(visible[0].target.id)
      },
      { rootMargin: '0px 0px -70% 0px' },
    )
    targets.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
  }, [html, headings])

  // 站內連結在應用內導頁；其餘交給瀏覽器
  const onArticleClick = useCallback((event: React.MouseEvent<HTMLDivElement>) => {
    const anchor = (event.target as HTMLElement).closest('a[data-guide-link], a[data-external]') as HTMLAnchorElement | null
    if (!anchor) return
    event.preventDefault()
    if (anchor.dataset.external) window.open(anchor.href, '_blank', 'noopener,noreferrer')
    else navigate(anchor.dataset.guideLink ?? '/help')
  }, [navigate])

  const nav = page === TOOLS ? {} : neighbours(page)
  const pageLabel = (p: GuidePage) => t(`help.pages.${p}`)

  return (
    <Page>
      <PageHeader title={t('help.title')} description={t('help.subtitle')} />
      <div className="relative mb-3 max-w-xl">
        <Search size={14} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input
          className="input pl-8"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('help.search')}
          data-testid="help-search"
        />
        {query.trim() ? (
          <div className="card absolute z-20 mt-1 max-h-80 w-full overflow-y-auto p-1" data-testid="help-search-results">
            {hits.length ? hits.map((h) => (
              <button
                key={`${h.page}-${h.id}-${h.snippet.slice(0, 12)}`}
                type="button"
                className="block w-full rounded-md px-3 py-2 text-left hover:bg-surface-muted"
                onClick={() => { setQuery(''); navigate(`/help/${h.page}${h.id ? `#${h.id}` : ''}`) }}
              >
                <span className="text-xs font-semibold text-heading">{pageLabel(h.page)}{h.heading ? ` › ${h.heading}` : ''}</span>
                <span className="mt-0.5 block text-xs text-muted">{h.snippet}</span>
              </button>
            )) : <p className="px-3 py-2 text-xs text-muted">{corpus ? t('help.searchEmpty') : '…'}</p>}
          </div>
        ) : null}
      </div>
      <div className="flex gap-6" data-testid="help-page">
        <aside className="hidden w-60 shrink-0 md:block" data-testid="help-nav">
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted">{t('help.pagesTitle')}</p>
          <ul className="space-y-0.5 text-sm">
            {GUIDE_PAGES.map((p) => (
              <li key={p}>
                <Link to={`/help/${p}`} className={`flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-surface-muted ${p === page ? 'bg-surface-muted font-semibold text-heading' : 'text-content'}`}>
                  <BookOpen size={13} className="shrink-0 text-muted" />{pageLabel(p)}
                </Link>
              </li>
            ))}
            <li>
              <Link to={`/help/${TOOLS}`} className={`flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-surface-muted ${page === TOOLS ? 'bg-surface-muted font-semibold text-heading' : 'text-content'}`}>
                <Wrench size={13} className="shrink-0 text-muted" />{t('help.toolsCatalogue')}
              </Link>
            </li>
          </ul>
          {page !== TOOLS && headings.length ? (
            <>
              <p className="mb-1.5 mt-4 text-[11px] font-semibold uppercase tracking-wide text-muted">{t('help.sections')}</p>
              <ul className="space-y-0.5 border-l border-line text-xs" data-testid="help-toc">
                {headings.map((h) => (
                  <li key={h.id}>
                    <a
                      href={`#${h.id}`}
                      onClick={(e) => { e.preventDefault(); navigate(`/help/${page}#${h.id}`) }}
                      className={`block truncate border-l-2 py-1 pr-1 hover:text-heading ${h.level === 3 ? 'pl-5' : 'pl-3'} ${active === h.id ? 'border-brand text-heading' : 'border-transparent text-muted'}`}
                      title={h.text}
                    >
                      {h.text}
                    </a>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </aside>
        <div className="min-w-0 flex-1">
          {/* 手機：頁面下拉 */}
          <select className="input mb-3 md:hidden" value={page} onChange={(e) => navigate(`/help/${e.target.value}`)} aria-label={t('help.pagesTitle')}>
            {GUIDE_PAGES.map((p) => <option key={p} value={p}>{pageLabel(p)}</option>)}
            <option value={TOOLS}>{t('help.toolsCatalogue')}</option>
          </select>
          {page === TOOLS ? <ToolsCatalogue /> : (
            <>
              {guide?.fallback ? <p className="mb-3 rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-xs text-warning" data-testid="help-fallback">{t('help.fallbackNotice')}</p> : null}
              {error ? <p className="text-sm text-danger">{error}</p> : null}
              <article ref={articleRef} className="guide-article" data-testid="help-article" onClick={onArticleClick} dangerouslySetInnerHTML={{ __html: html }} />
              {guide ? (
                <div className="mt-6 flex items-center justify-between border-t border-line pt-4">
                  {nav.prev ? <Button size="sm" variant="secondary" icon={<ChevronLeft size={14} />} onClick={() => navigate(`/help/${nav.prev}`)}>{t('help.prev')}: {pageLabel(nav.prev)}</Button> : <span />}
                  {nav.next ? <Button size="sm" variant="secondary" onClick={() => navigate(`/help/${nav.next}`)}>{t('help.next')}: {pageLabel(nav.next)} <ChevronRight size={14} /></Button> : <span />}
                </div>
              ) : null}
              <span className="sr-only">{title}</span>
            </>
          )}
        </div>
      </div>
    </Page>
  )
}
