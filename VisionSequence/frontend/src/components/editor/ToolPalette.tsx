/**
 * 左欄上半：工具箱（ToolPalette）。步驟清單在 NodeList.tsx。
 * 工具一律「拖曳到畫布」新增（DRAG_MIME）；點擊工具沒有動作（title 顯示工具說明）。
 * 工具箱最上方有「收藏」（星號，localStorage vs.favoriteTools）。
 */
import { useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, Search, Star } from 'lucide-react'

import type { ToolCatalogue, ToolTypeDef } from '@/lib/types'
import { DRAG_MIME } from './graphMapping'
import { iconFor } from './ToolNode'

export const FAVORITES_KEY = 'vs.favoriteTools'

function readList(key: string): string[] {
  try {
    const raw = localStorage.getItem(key)
    const parsed = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : []
  } catch {
    return []
  }
}

function writeList(key: string, list: string[]) {
  try {
    localStorage.setItem(key, JSON.stringify(list))
  } catch {
    /* ignore */
  }
}

function ToolButton({ def, favorite, onToggleFavorite }: { def: ToolTypeDef; favorite: boolean; onToggleFavorite: (key: string) => void }) {
  const { t } = useTranslation()
  const Icon = iconFor(def.icon)
  return (
    <div className="group flex items-center rounded hover:bg-surface-muted" data-testid="palette-tool" data-tool-key={def.key}>
      <button
        type="button"
        title={def.description ? `${def.description}\n${t('editor.paletteHint')}` : t('editor.paletteHint')}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData(DRAG_MIME, def.key)
          e.dataTransfer.effectAllowed = 'copy'
        }}
        className="flex min-w-0 flex-1 cursor-grab select-none items-center gap-2 px-2 py-1 text-left text-xs active:cursor-grabbing"
      >
        <Icon size={14} className="shrink-0 text-brand" aria-hidden />
        <span className="truncate">{def.label}</span>
      </button>
      <button
        type="button"
        className={`mr-1 rounded p-0.5 ${favorite ? 'text-warning' : 'text-subtle opacity-0 group-hover:opacity-100'}`}
        aria-label={favorite ? t('palette.unfavorite') : t('palette.favorite')}
        title={favorite ? t('palette.unfavorite') : t('palette.favorite')}
        aria-pressed={favorite}
        onClick={() => onToggleFavorite(def.key)}
        data-testid="palette-star"
      >
        <Star size={12} fill={favorite ? 'currentColor' : 'none'} />
      </button>
    </div>
  )
}

export function ToolPalette({ catalogue }: { catalogue: ToolCatalogue | undefined }) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(() => new Set())
  const [favorites, setFavorites] = useState<string[]>(() => readList(FAVORITES_KEY))

  const toggleFavorite = useCallback((key: string) => {
    setFavorites((old) => {
      const next = old.includes(key) ? old.filter((k) => k !== key) : [...old, key]
      writeList(FAVORITES_KEY, next)
      return next
    })
  }, [])

  const byKey = useMemo(() => new Map((catalogue?.items ?? []).map((d) => [d.key, d])), [catalogue])
  const groups = useMemo(() => {
    const q = query.trim().toLowerCase()
    const map = new Map<string, { label: string; items: ToolTypeDef[] }>()
    for (const def of catalogue?.items ?? []) {
      if (q && !`${def.label} ${def.key} ${def.description}`.toLowerCase().includes(q)) continue
      const g = map.get(def.category) ?? { label: def.category_label, items: [] }
      g.items.push(def)
      map.set(def.category, g)
    }
    return map
  }, [catalogue, query])

  const favDefs = favorites.map((k) => byKey.get(k)).filter((d): d is ToolTypeDef => Boolean(d))

  const section = (key: string, label: string, items: ToolTypeDef[], empty?: string) => {
    const isCollapsed = collapsed.has(key) && !query
    return (
      <div key={key} className="mb-1" data-testid={`palette-${key}`}>
        <button
          type="button"
          className="flex w-full items-center gap-1 rounded px-1 py-1 text-[11px] font-medium uppercase tracking-wide text-muted hover:bg-surface-muted"
          onClick={() =>
            setCollapsed((old) => {
              const next = new Set(old)
              if (next.has(key)) next.delete(key)
              else next.add(key)
              return next
            })
          }
        >
          {isCollapsed ? <ChevronRight size={12} /> : <ChevronDown size={12} />}
          {label}
          <span className="ml-auto tabular-nums text-subtle">{items.length}</span>
        </button>
        {isCollapsed ? null : items.length ? items.map((def) => <ToolButton key={def.key} def={def} favorite={favorites.includes(def.key)} onToggleFavorite={toggleFavorite} />) : empty ? <p className="px-2 py-1 text-[11px] text-subtle">{empty}</p> : null}
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      <div className="relative p-2">
        <Search size={13} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-subtle" />
        <input className="input !py-1 !pl-7 text-xs" placeholder={t('editor.searchTools')} value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {!query ? section('favorites', t('palette.favorites'), favDefs, t('palette.noFavorites')) : null}
        {[...groups.entries()].map(([category, group]) => section(category, group.label, group.items))}
      </div>
    </div>
  )
}
