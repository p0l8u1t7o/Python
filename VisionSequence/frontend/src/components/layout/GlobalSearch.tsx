/**
 * 全域搜尋（GlobalSearch）：頂部導覽列右側的搜尋框，搜尋全平台內容。
 * 範圍：頁面、流程、工具（調色盤）、影像來源、連線、資產。Ctrl+K 聚焦、↑↓ 選擇、Enter 前往、Esc 關閉。
 * 資料直接用既有 API（皆已依身分過濾）：輸入時才發查詢，結果由 react-query 快取。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useQuery } from '@tanstack/react-query'
import { Brain, Cable, Camera, FileText, FlaskConical, Images, LayoutDashboard, Plug, Search, Settings, Sparkles, Users, Workflow, Wrench } from 'lucide-react'

import { api } from '@/lib/api'
import { useAuth } from '@/providers/AuthProvider'
import type { Asset, Connection, Flow, ImageSource, Page, ToolCatalogue } from '@/lib/types'

const PAGES = [
  { to: '/', key: 'dashboard', icon: LayoutDashboard, admin: false },
  { to: '/flows', key: 'flows', icon: Workflow, admin: false },
  { to: '/batch', key: 'batch', icon: FlaskConical, admin: false },
  { to: '/sources', key: 'sources', icon: Camera, admin: false },
  { to: '/assets', key: 'assets', icon: Images, admin: false },
  { to: '/dl', key: 'dl', icon: Brain, admin: false },
  { to: '/agent', key: 'agent', icon: Sparkles, admin: false },
  { to: '/integration', key: 'integration', icon: Plug, admin: false },
  { to: '/users', key: 'users', icon: Users, admin: true },
  { to: '/settings', key: 'settings', icon: Settings, admin: false },
  { to: '/help', key: 'help', icon: FileText, admin: false },
] as const

interface Hit {
  group: 'pages' | 'flows' | 'tools' | 'sources' | 'connections' | 'assets'
  label: string
  sub?: string
  to: string
  icon: React.ComponentType<{ size?: number | string; className?: string }>
}

const PER_GROUP = 5

function matches(q: string, ...fields: (string | undefined)[]): boolean {
  return fields.some((f) => (f || '').toLowerCase().includes(q))
}

export function GlobalSearch() {
  const { t } = useTranslation()
  const auth = useAuth()
  const navigate = useNavigate()
  const inputRef = useRef<HTMLInputElement>(null)
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  //: 頂列預設只顯示放大鏡 icon；點擊（或 Ctrl+K）才展開輸入框，清空離開時收回
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    if (expanded) inputRef.current?.focus()
  }, [expanded])

  useEffect(() => {
    const id = setTimeout(() => setDebounced(q.trim()), 250)
    return () => clearTimeout(id)
  }, [q])

  // Ctrl+K / Cmd+K 聚焦
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setExpanded(true) // 收合時先展開；已展開時 effect 不重跑，直接聚焦
        inputRef.current?.focus()
        inputRef.current?.select()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const enabled = open && debounced.length > 0
  const flows = useQuery({
    queryKey: ['search', 'flows', debounced],
    queryFn: () => api.get<Page<Flow>>('/vision/flows', { q: debounced, limit: 20 }),
    enabled,
  })
  const sources = useQuery({
    queryKey: ['sources'],
    queryFn: () => api.get<{ items: ImageSource[] }>('/vision/sources'),
    enabled,
    staleTime: 30_000,
  })
  const connections = useQuery({
    queryKey: ['connections'],
    queryFn: () => api.get<{ items: Connection[] }>('/vision/connections'),
    enabled,
    staleTime: 30_000,
  })
  const assets = useQuery({
    queryKey: ['assets', ''],
    queryFn: () => api.get<{ items: Asset[] }>('/vision/assets', { kind: '' }),
    enabled,
    staleTime: 30_000,
  })
  const tools = useQuery({
    queryKey: ['tool-types'],
    queryFn: () => api.get<ToolCatalogue>('/vision/tool-types'),
    enabled,
    staleTime: 5 * 60_000,
  })

  const hits = useMemo<Hit[]>(() => {
    const query = debounced.toLowerCase()
    if (!query) return []
    const out: Hit[] = []
    for (const p of PAGES) {
      if (p.admin && !auth.isAdmin) continue
      const label = t(`nav.${p.key}`)
      if (matches(query, label, p.key)) out.push({ group: 'pages', label, to: p.to, icon: p.icon })
    }
    for (const f of (flows.data?.items ?? []).slice(0, PER_GROUP)) {
      out.push({ group: 'flows', label: f.name, sub: f.description || `#${f.id}`, to: `/flows/${f.id}`, icon: Workflow })
    }
    for (const tt of (tools.data?.items ?? []).filter((x) => matches(query, x.label, x.key, x.description)).slice(0, PER_GROUP)) {
      out.push({ group: 'tools', label: tt.label, sub: tt.key, to: '/help?tab=tools', icon: Wrench })
    }
    for (const s of (sources.data?.items ?? []).filter((x) => matches(query, x.name, x.kind)).slice(0, PER_GROUP)) {
      out.push({ group: 'sources', label: s.name, sub: s.kind, to: '/sources', icon: Camera })
    }
    for (const c of (connections.data?.items ?? []).filter((x) => matches(query, x.name, x.kind)).slice(0, PER_GROUP)) {
      // 連線由用到它的整合頁管理：Modbus 系的到 Modbus 頁，其餘（上位機 TCP、外掛）到 TCP 頁
      out.push({ group: 'connections', label: c.name, sub: c.kind, to: c.kind === 'modbus_server' ? '/integration/modbus-server' : c.kind === 'modbus_tcp' ? '/integration/modbus-client' : '/integration/tcp', icon: Cable })
    }
    for (const a of (assets.data?.items ?? []).filter((x) => matches(query, x.name, x.kind)).slice(0, PER_GROUP)) {
      out.push({ group: 'assets', label: a.name, sub: a.kind, to: '/assets', icon: Images })
    }
    return out
  }, [debounced, auth.isAdmin, t, flows.data, tools.data, sources.data, connections.data, assets.data])

  useEffect(() => setActive(0), [debounced])

  function go(hit: Hit) {
    setOpen(false)
    setQ('')
    navigate(hit.to)
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((v) => Math.min(v + 1, hits.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((v) => Math.max(v - 1, 0))
    } else if (e.key === 'Enter') {
      const hit = hits[active] ?? hits[0]
      if (hit) go(hit)
    } else if (e.key === 'Escape') {
      setOpen(false)
      inputRef.current?.blur()
    }
  }

  const loading = enabled && (flows.isLoading || tools.isLoading)
  let lastGroup = ''
  if (!expanded) {
    return (
      <button type="button" className="btn-icon hidden sm:block" onClick={() => setExpanded(true)}
        title={`${t('search.placeholder')} (Ctrl K)`} aria-label={t('search.placeholder')} data-testid="global-search">
        <Search size={16} />
      </button>
    )
  }
  return (
    <div className="relative hidden sm:block" data-testid="global-search">
      <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted" aria-hidden />
      <input
        ref={inputRef}
        type="search"
        value={q}
        onChange={(e) => {
          setQ(e.target.value)
          setOpen(true)
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => {
          setOpen(false)
          if (!inputRef.current?.value.trim()) setExpanded(false) // 空的就收回 icon
        }, 150)}
        onKeyDown={onKeyDown}
        placeholder={t('search.placeholder')}
        aria-label={t('search.placeholder')}
        className="h-8 w-72 rounded-md border border-brand bg-surface pl-8 pr-12 text-[13px] text-content outline-none placeholder:text-subtle"
        data-testid="global-search-input"
      />
      <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-line bg-surface px-1 text-[10px] text-subtle">Ctrl K</kbd>
      {open && q.trim() ? (
        <div className="absolute right-0 top-full z-40 mt-1 max-h-[70vh] w-96 overflow-y-auto rounded-md border border-line bg-surface py-1 text-sm shadow-lg" role="listbox" data-testid="global-search-results">
          {hits.length === 0 ? (
            <p className="px-3 py-2.5 text-[13px] text-muted">{loading ? t('search.searching') : t('search.noResults', { q: q.trim() })}</p>
          ) : (
            hits.map((hit, i) => {
              const header = hit.group !== lastGroup ? t(`search.groups.${hit.group}`) : null
              lastGroup = hit.group
              const Icon = hit.icon
              return (
                <div key={`${hit.group}-${hit.to}-${hit.label}-${i}`}>
                  {header ? <p className="px-3 pb-0.5 pt-2 text-[10px] font-semibold uppercase tracking-wider text-subtle">{header}</p> : null}
                  <button
                    type="button"
                    role="option"
                    aria-selected={i === active}
                    className={`flex w-full items-center gap-2.5 px-3 py-1.5 text-left ${i === active ? 'bg-surface-muted' : 'hover:bg-surface-muted'}`}
                    onMouseDown={(e) => {
                      e.preventDefault()
                      go(hit)
                    }}
                    onMouseEnter={() => setActive(i)}
                  >
                    <Icon size={15} className="shrink-0 text-muted" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-content">{hit.label}</span>
                      {hit.sub ? <span className="block truncate text-xs text-muted">{hit.sub}</span> : null}
                    </span>
                  </button>
                </div>
              )
            })
          )}
        </div>
      ) : null}
    </div>
  )
}
