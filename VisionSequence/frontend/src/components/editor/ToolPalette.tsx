/**
 * 工具選擇：工具數量多，左欄不再放完整清單——
 * - FavoriteTools（左欄）：收藏的常用工具（可拖曳到畫布、點擊插入畫布中央）。
 * - ToolPicker（Modal）：大圖示＋完整說明的選擇視窗，左側功能分群快速切換、可搜尋、可收藏。
 * 收藏狀態由 FlowEditorPage 提升管理（localStorage vs.favoriteTools），兩邊即時同步。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Plus, Search, Star, StickyNote } from 'lucide-react'

import { Modal } from '@/components/ui'
import type { ToolCatalogue, ToolTypeDef } from '@/lib/types'
import { DRAG_MIME } from './graphMapping'
import { iconFor } from './ToolNode'

export const FAVORITES_KEY = 'vs.favoriteTools'

export function readFavorites(): string[] {
  try {
    const raw = localStorage.getItem(FAVORITES_KEY)
    const parsed = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(parsed) ? parsed.filter((v): v is string => typeof v === 'string') : []
  } catch {
    return []
  }
}

export function writeFavorites(list: string[]) {
  try {
    localStorage.setItem(FAVORITES_KEY, JSON.stringify(list))
  } catch {
    /* ignore */
  }
}

/** 左欄：新增工具／註解按鈕＋收藏清單（可拖曳；點擊直接插入畫布中央）。 */
export function FavoriteTools({ catalogue, favorites, onOpenPicker, onInsert, onAddNote }: {
  catalogue: ToolCatalogue | undefined
  favorites: string[]
  onOpenPicker: () => void
  onInsert: (def: ToolTypeDef) => void
  onAddNote: () => void
}) {
  const { t } = useTranslation()
  const byKey = useMemo(() => new Map((catalogue?.items ?? []).map((d) => [d.key, d])), [catalogue])
  const favDefs = favorites.map((k) => byKey.get(k)).filter((d): d is ToolTypeDef => Boolean(d))
  return (
    <div className="flex h-full flex-col gap-2 p-2">
      <button type="button" onClick={onOpenPicker} data-testid="btn-add-tool"
        className="btn-primary w-full !justify-center !py-2 text-sm">
        <Plus size={16} /> {t('palette.addTool')}
      </button>
      <button type="button" onClick={onAddNote} data-testid="btn-add-note"
        className="btn w-full !justify-center !py-1.5 text-xs" title={t('palette.addNoteHint')}>
        <StickyNote size={14} /> {t('palette.addNote')}
      </button>
      <p className="px-1 text-[11px] font-medium uppercase tracking-wide text-muted">{t('palette.favorites')}</p>
      <div className="min-h-0 flex-1 space-y-0.5 overflow-y-auto">
        {favDefs.map((def) => {
          const Icon = iconFor(def.icon)
          return (
            <button key={def.key} type="button" title={`${def.description}\n${t('palette.favClickHint')}`}
              draggable
              onDragStart={(e) => {
                e.dataTransfer.setData(DRAG_MIME, def.key)
                e.dataTransfer.effectAllowed = 'copy'
              }}
              onClick={() => onInsert(def)}
              className="flex w-full cursor-grab select-none items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs hover:bg-surface-muted active:cursor-grabbing"
              data-testid="palette-tool" data-tool-key={def.key}>
              <Icon size={14} className="shrink-0 text-brand" aria-hidden />
              <span className="truncate">{def.label}</span>
            </button>
          )
        })}
        {!favDefs.length ? <p className="px-2 py-1 text-[11px] text-subtle">{t('palette.noFavorites')}</p> : null}
      </div>
    </div>
  )
}

/** 工具選擇視窗：左＝功能分群、右＝大圖示卡片（完整說明）；點卡插入畫布並關閉。 */
export function ToolPicker({ open, onClose, catalogue, favorites, onToggleFavorite, onPick }: {
  open: boolean
  onClose: () => void
  catalogue: ToolCatalogue | undefined
  favorites: string[]
  onToggleFavorite: (key: string) => void
  onPick: (def: ToolTypeDef) => void
}) {
  const { t } = useTranslation()
  const [query, setQuery] = useState('')
  const [category, setCategory] = useState('__all__')

  const groups = useMemo(() => {
    const map = new Map<string, { label: string; items: ToolTypeDef[] }>()
    for (const def of catalogue?.items ?? []) {
      const g = map.get(def.category) ?? { label: def.category_label, items: [] }
      g.items.push(def)
      map.set(def.category, g)
    }
    return map
  }, [catalogue])

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase()
    let items = catalogue?.items ?? []
    if (q) {
      // 搜尋跨全部分類
      return items.filter((d) => `${d.label} ${d.key} ${d.description}`.toLowerCase().includes(q))
    }
    if (category === '__fav__') items = items.filter((d) => favorites.includes(d.key))
    else if (category !== '__all__') items = items.filter((d) => d.category === category)
    return items
  }, [catalogue, query, category, favorites])

  const tab = (key: string, label: string, count: number) => (
    <button key={key} type="button" onClick={() => { setCategory(key); setQuery('') }} aria-pressed={category === key && !query}
      className={`flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors
        ${category === key && !query ? 'bg-brand-soft font-medium text-brand' : 'text-content hover:bg-surface-muted'}`}
      data-testid={`picker-cat-${key}`}>
      <span className="truncate">{label}</span>
      <span className="tnum text-xs text-muted">{count}</span>
    </button>
  )

  return (
    <Modal open={open} onClose={onClose} title={t('palette.pickerTitle')} size="lg">
      <div className="grid h-[70vh] min-h-0 grid-cols-[170px_minmax(0,1fr)] gap-3 overflow-hidden" data-testid="tool-picker">
        {/* 左：功能分群 */}
        <div className="min-h-0 space-y-1 overflow-y-auto pr-1">
          {tab('__all__', t('palette.allTools'), catalogue?.items.length ?? 0)}
          {tab('__fav__', t('palette.favorites'), favorites.length)}
          <div className="my-1 h-px bg-line" />
          {[...groups.entries()].map(([key, g]) => tab(key, g.label, g.items.length))}
        </div>
        {/* 右：搜尋＋大卡 */}
        <div className="flex min-h-0 flex-col gap-2">
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle" />
            <input className="input !pl-8" placeholder={t('editor.searchTools')} value={query} autoFocus
              onChange={(e) => setQuery(e.target.value)} data-testid="picker-search" />
          </div>
          <div className="grid min-h-0 flex-1 auto-rows-min grid-cols-1 gap-2.5 overflow-y-auto pr-1 sm:grid-cols-2 xl:grid-cols-3">
            {shown.map((def) => {
              const Icon = iconFor(def.icon)
              const fav = favorites.includes(def.key)
              return (
                <div key={def.key} className="group relative">
                  <button type="button" onClick={() => onPick(def)} title={t('palette.pickHint')}
                    className="flex h-full w-full flex-col gap-1.5 rounded-lg border border-line bg-surface p-3 text-left transition-all hover:-translate-y-px hover:border-brand hover:shadow-md"
                    data-testid={`picker-tool-${def.key}`}>
                    <span className="flex items-center gap-2.5">
                      <span className="flex size-10 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand">
                        <Icon size={22} aria-hidden />
                      </span>
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold">{def.label}</span>
                        <span className="block font-mono text-[10px] text-subtle">{def.key}{def.heavy ? ` · ${t('editor.heavy')}` : ''}</span>
                      </span>
                    </span>
                    <span className="line-clamp-3 text-xs leading-relaxed text-muted">{def.description}</span>
                  </button>
                  <button type="button" onClick={() => onToggleFavorite(def.key)} aria-pressed={fav}
                    aria-label={fav ? t('palette.unfavorite') : t('palette.favorite')} title={fav ? t('palette.unfavorite') : t('palette.favorite')}
                    className={`absolute right-2 top-2 rounded p-1 ${fav ? 'text-warning' : 'text-subtle opacity-0 group-hover:opacity-100'}`}>
                    <Star size={14} fill={fav ? 'currentColor' : 'none'} />
                  </button>
                </div>
              )
            })}
            {!shown.length ? <p className="col-span-full py-6 text-center text-sm text-subtle">{t('palette.noResults')}</p> : null}
          </div>
        </div>
      </div>
    </Modal>
  )
}
