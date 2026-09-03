/**
 * 工具選擇：工具數量多，左欄不再放完整清單——
 * - FavoriteTools（左欄）：收藏的常用工具（可拖曳到畫布、點擊插入畫布中央）。
 * - ToolPicker（Modal）：大圖示＋完整說明的選擇視窗，左側功能分群快速切換、可搜尋、可收藏。
 * 收藏狀態由 FlowEditorPage 提升管理（localStorage vs.favoriteTools），兩邊即時同步。
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronLeft, Info, Plus, Search, Star, StickyNote, X } from 'lucide-react'

import { Button, IconButton, Modal } from '@/components/ui'
import { PORT_HEX } from '@/lib/ports'
import { MOBILE_QUERY, useMediaQuery } from '@/lib/useMediaQuery'
import type { ToolCatalogue, ToolParam, ToolPort, ToolTypeDef } from '@/lib/types'
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

/** 左欄：新增工具／註解按鈕＋收藏清單（可拖曳；點擊插入畫布中央；hover 出現移除鈕）。 */
export function FavoriteTools({ catalogue, favorites, onOpenPicker, onInsert, onAddNote, onToggleFavorite }: {
  catalogue: ToolCatalogue | undefined
  favorites: string[]
  onOpenPicker: () => void
  onInsert: (def: ToolTypeDef) => void
  onAddNote: () => void
  onToggleFavorite: (key: string) => void
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
            <div key={def.key} className="group relative">
              <button type="button" title={`${def.description}\n${t('palette.favClickHint')}`}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData(DRAG_MIME, def.key)
                  e.dataTransfer.effectAllowed = 'copy'
                }}
                onClick={() => onInsert(def)}
                className="flex w-full cursor-grab select-none items-center gap-2 rounded-md px-2 py-1.5 pr-7 text-left text-xs hover:bg-surface-muted active:cursor-grabbing"
                data-testid="palette-tool" data-tool-key={def.key}>
                <Icon size={14} className="shrink-0 text-brand" aria-hidden />
                <span className="truncate">{def.label}</span>
              </button>
              <button type="button" onClick={(e) => { e.stopPropagation(); onToggleFavorite(def.key) }}
                aria-label={t('palette.unfavorite')} title={t('palette.unfavorite')}
                className="absolute right-1 top-1/2 -translate-y-1/2 rounded p-1 text-subtle opacity-0 transition-opacity hover:bg-surface-muted hover:text-critical group-hover:opacity-100"
                data-testid="palette-unfav" data-tool-key={def.key}>
                <X size={12} aria-hidden />
              </button>
            </div>
          )
        })}
        {!favDefs.length ? <p className="px-2 py-1 text-[11px] text-subtle">{t('palette.noFavorites')}</p> : null}
      </div>
    </div>
  )
}

/**
 * 工具選擇視窗（接近全螢幕的視窗、三欄各自捲動）：
 *   左＝功能分類｜中＝工具格（3 欄 n 列的卡片：圖示＋名稱完整顯示＋key，不放敘述）｜右＝點選工具的完整詳細說明（說明全文、輸入／輸出埠、參數表）。
 * 點卡片＝看詳細；「加入畫布」或雙擊＝插入並關閉。窄螢幕改為上下堆疊（分類變晶片列、格子變 2 欄）。
 */
function PortList({ ports, side }: { ports: ToolPort[]; side: 'in' | 'out' }) {
  const { t } = useTranslation()
  const shown = side === 'in' ? ports : [...ports].sort((a, b) => Number(a.implicit === true) - Number(b.implicit === true))
  return (
    <div>
      <p className="label !mb-1">{side === 'in' ? t('editor.inputs') : t('editor.outputs')}</p>
      {shown.length ? (
        <ul className="space-y-1">
          {shown.map((port) => (
            <li key={port.key} className={`flex items-baseline gap-2 text-xs ${port.implicit ? 'opacity-70' : ''}`}>
              <span className={`mt-1 inline-block size-2 shrink-0 ${port.type === 'flow' ? 'rotate-45' : 'rounded-full'}`} style={{ background: PORT_HEX[port.type] }} aria-hidden />
              <span className="min-w-0">
                <span className="text-content">{port.label}</span>
                {port.required && side === 'in' ? <span className="text-critical">*</span> : null}
                <span className="ml-1.5 font-mono text-[10px] text-subtle">{port.type}</span>
                {port.multiple ? <span className="ml-1 text-[10px] text-subtle">{t('palette.multiplePort')}</span> : null}
              </span>
            </li>
          ))}
        </ul>
      ) : <p className="text-xs text-subtle">—</p>}
    </div>
  )
}

/** 參數表：名稱（必填星號）、型別／單位、預設值、範圍、現場教導標記、說明。 */
function ParamTable({ params }: { params: ToolParam[] }) {
  const { t } = useTranslation()
  const fmt = (v: unknown) => {
    if (v === null || v === undefined || v === '') return '—'
    if (typeof v === 'object') return Array.isArray(v) ? `[${v.length}]` : '{…}'
    return String(v)
  }
  const range = (param: ToolParam) => {
    const lo = param.minimum, hi = param.maximum
    if (lo === null && hi === null) return ''
    return `${lo ?? '−∞'} ~ ${hi ?? '∞'}`
  }
  return (
    <div>
      <p className="label !mb-1">{t('editor.parameters')} <span className="tnum font-normal">({params.length})</span></p>
      {params.length ? (
        <div className="overflow-hidden rounded-md border border-line">
          <table className="w-full border-collapse text-xs">
            <thead className="bg-surface-muted/50 text-[11px] text-muted">
              <tr>
                <th scope="col" className="px-2 py-1 text-left font-semibold">{t('common.name')}</th>
                <th scope="col" className="px-2 py-1 text-left font-semibold">{t('palette.paramKind')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-1 text-left font-semibold">{t('palette.paramDefault')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {params.map((param) => (
                <tr key={param.key} className="align-top">
                  <td className="px-2 py-1.5">
                    <span className="font-medium text-content">{param.label}</span>
                    {param.required ? <span className="text-critical">*</span> : null}
                    {param.teach ? <span className="ml-1 rounded bg-brand-soft px-1 text-[10px] text-brand">{t('palette.paramTeach')}</span> : null}
                    <span className="block font-mono text-[10px] text-subtle">{param.key}</span>
                    {param.help_text ? <span className="mt-0.5 block text-[11px] leading-snug text-muted">{param.help_text}</span> : null}
                  </td>
                  <td className="px-2 py-1.5 text-muted">
                    <span className="font-mono text-[11px]">{param.kind}</span>
                    {param.unit ? <span className="ml-1 text-[11px]">（{param.unit}）</span> : null}
                    {range(param) ? <span className="tnum block text-[10px] text-subtle">{range(param)}</span> : null}
                    {param.options.length ? <span className="block text-[10px] text-subtle">{param.options.map((o) => o.label).join('／')}</span> : null}
                  </td>
                  <td className="tnum max-w-44 truncate whitespace-nowrap px-2 py-1.5 font-mono text-[11px] text-muted" title={fmt(param.default)}>{fmt(param.default)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p className="text-xs text-subtle">{t('palette.noParams')}</p>}
    </div>
  )
}

/** 右欄：選中工具的完整說明。沒選就給提示。 */
function ToolDetail({ def, fav, onToggleFavorite, onPick }: { def: ToolTypeDef | null; fav: boolean; onToggleFavorite: (key: string) => void; onPick: (def: ToolTypeDef) => void }) {
  const { t } = useTranslation()
  if (!def) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center text-sm text-subtle" data-testid="picker-detail-empty">
        <Info size={22} aria-hidden />
        <p>{t('palette.detailHint')}</p>
      </div>
    )
  }
  const Icon = iconFor(def.icon)
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="picker-detail" data-tool-key={def.key}>
      <div className="flex items-start gap-3 border-b border-line px-4 py-3">
        <span className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-brand-soft text-brand">
          <Icon size={24} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          {/* 名稱完整顯示（會換行），不用 truncate */}
          <h3 className="text-base font-semibold leading-snug text-heading [overflow-wrap:anywhere]">{def.label}</h3>
          <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-muted">
            <span className="font-mono text-subtle">{def.key}</span>
            <span>·</span>
            <span>{def.category_label}</span>
            {def.heavy ? <span className="rounded bg-warning-soft px-1.5 text-warning">{t('editor.heavy')}</span> : null}
          </p>
        </div>
        <IconButton label={fav ? t('palette.unfavorite') : t('palette.favorite')} onClick={() => onToggleFavorite(def.key)} active={fav} className={fav ? '!text-warning' : ''} data-testid="picker-detail-fav">
          <Star size={16} fill={fav ? 'currentColor' : 'none'} />
        </IconButton>
      </div>
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-3">
        {def.description ? <p className="whitespace-pre-line text-sm leading-relaxed text-content" data-testid="picker-detail-desc">{def.description}</p> : null}
        <div className="grid gap-4 sm:grid-cols-2">
          <PortList ports={def.inputs} side="in" />
          <PortList ports={def.outputs} side="out" />
        </div>
        <ParamTable params={def.params} />
      </div>
      <div className="border-t border-line px-4 py-3">
        <Button variant="primary" className="w-full" icon={<Plus size={15} />} onClick={() => onPick(def)} data-testid="picker-insert">{t('palette.insertTool')}</Button>
      </div>
    </div>
  )
}

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
  const [selected, setSelected] = useState<string | null>(null)
  const mobile = useMediaQuery(MOBILE_QUERY)

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
    if (q) return items.filter((d) => `${d.label} ${d.key} ${d.description}`.toLowerCase().includes(q))  // 搜尋跨全部分類
    if (category === '__fav__') items = items.filter((d) => favorites.includes(d.key))
    else if (category !== '__all__') items = items.filter((d) => d.category === category)
    return items
  }, [catalogue, query, category, favorites])

  // 清單變了就把選取移到第一個（桌面永遠有詳細可看；手機不預選，先讓使用者挑）
  useEffect(() => {
    if (!open) return
    if (mobile) return
    if (!shown.length) { setSelected(null); return }
    if (!selected || !shown.some((d) => d.key === selected)) setSelected(shown[0].key)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, mobile, shown])
  useEffect(() => { if (!open) { setSelected(null); setQuery('') } }, [open])

  const current = shown.find((d) => d.key === selected) ?? (catalogue?.items ?? []).find((d) => d.key === selected) ?? null

  const catButton = (key: string, label: string, count: number) => {
    const active = category === key && !query
    return (
      <button key={key} type="button" onClick={() => { setCategory(key); setQuery('') }} aria-pressed={active}
        className={mobile
          ? `flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors ${active ? 'border-brand bg-brand-soft font-medium text-brand' : 'border-line text-muted hover:bg-surface-muted'}`
          : `flex w-full items-center justify-between gap-2 rounded-md px-3 py-2 text-left text-sm transition-colors ${active ? 'bg-brand-soft font-medium text-brand' : 'text-content hover:bg-surface-muted'}`}
        data-testid={`picker-cat-${key}`}>
        <span className={mobile ? '' : 'min-w-0 flex-1'}>{label}</span>
        <span className="tnum text-xs text-muted">{count}</span>
      </button>
    )
  }
  const categories = (
    <>
      {catButton('__all__', t('palette.allTools'), catalogue?.items.length ?? 0)}
      {catButton('__fav__', t('palette.favorites'), favorites.length)}
      {mobile ? null : <div className="my-1 h-px bg-line" />}
      {[...groups.entries()].map(([key, g]) => catButton(key, g.label, g.items.length))}
    </>
  )

  const list = (
    <ul className="grid min-h-0 flex-1 auto-rows-min grid-cols-2 gap-2 overflow-y-auto p-2 md:grid-cols-3" data-testid="picker-list">
      {shown.map((def) => {
        const Icon = iconFor(def.icon)
        const active = def.key === selected
        const fav = favorites.includes(def.key)
        return (
          <li key={def.key} className="min-w-0">
            <button type="button" onClick={() => setSelected(def.key)} onDoubleClick={() => onPick(def)} aria-pressed={active}
              title={t('palette.pickHint')}
              className={`flex h-full w-full items-start gap-2.5 rounded-lg border px-3 py-2.5 text-left transition-colors
                ${active ? 'border-brand bg-brand-soft/40 shadow-sm' : 'border-line bg-surface hover:border-brand/50 hover:bg-surface-muted'}`}
              data-testid={`picker-tool-${def.key}`}>
              <span className={`mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-lg ${active ? 'bg-brand text-on-brand' : 'bg-brand-soft text-brand'}`}>
                <Icon size={18} aria-hidden />
              </span>
              <span className="min-w-0 flex-1">
                {/* 工具名稱完整顯示：長名稱換行，不截斷；敘述只在右欄 */}
                <span className="block text-sm font-medium leading-snug text-content [overflow-wrap:anywhere]">{def.label}</span>
                <span className="mt-0.5 block font-mono text-[10px] text-subtle [overflow-wrap:anywhere]">{def.key}{def.heavy ? ` · ${t('editor.heavy')}` : ''}</span>
              </span>
              {fav ? <Star size={12} className="mt-1 shrink-0 text-warning" fill="currentColor" aria-hidden /> : null}
            </button>
          </li>
        )
      })}
      {!shown.length ? <li className="col-span-full py-6 text-center text-sm text-subtle">{t('palette.noResults')}</li> : null}
    </ul>
  )

  return (
    <Modal open={open} onClose={onClose} title={t('palette.pickerTitle')} description={t('palette.pickerHint')} size="full">
      {mobile ? (
        <div className="flex h-[68vh] min-h-0 flex-col gap-2" data-testid="tool-picker">
          <div className="flex gap-1.5 overflow-x-auto pb-1">{categories}</div>
          <div className="relative">
            <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle" aria-hidden />
            <input className="input !pl-8" placeholder={t('editor.searchTools')} value={query} onChange={(e) => setQuery(e.target.value)} data-testid="picker-search" />
          </div>
          {current ? (
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-line">
              <button type="button" className="btn-ghost !justify-start gap-1 border-b border-line !rounded-none text-xs" onClick={() => setSelected(null)}>
                <ChevronLeft size={14} aria-hidden /> {t('palette.backToList')}
              </button>
              <ToolDetail def={current} fav={favorites.includes(current.key)} onToggleFavorite={onToggleFavorite} onPick={onPick} />
            </div>
          ) : (
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-line">{list}</div>
          )}
        </div>
      ) : (
        <div className="grid h-[78vh] min-h-0 grid-cols-[160px_minmax(0,1fr)_minmax(360px,460px)] gap-3 overflow-hidden" data-testid="tool-picker">
          {/* 左：分類 */}
          <div className="min-h-0 space-y-1 overflow-y-auto pr-1">{categories}</div>
          {/* 中：工具格（3 欄 n 列，名稱完整、不放敘述） */}
          <div className="flex min-h-0 flex-col gap-2">
            <div className="relative">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-subtle" aria-hidden />
              <input className="input !pl-8" placeholder={t('editor.searchTools')} value={query} autoFocus onChange={(e) => setQuery(e.target.value)} data-testid="picker-search" />
            </div>
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-line bg-surface-muted/30">{list}</div>
          </div>
          {/* 右：完整詳細說明 */}
          <div className="min-h-0 overflow-hidden rounded-lg border border-line bg-surface">
            <ToolDetail def={current} fav={current ? favorites.includes(current.key) : false} onToggleFavorite={onToggleFavorite} onPick={onPick} />
          </div>
        </div>
      )}
    </Modal>
  )
}
