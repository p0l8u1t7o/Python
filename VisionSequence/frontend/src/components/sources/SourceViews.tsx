/** 影像來源的兩種檢視：樹狀（種類→群組→來源，預設）與卡片（預覽縮圖）。
 * 兩種都保留表格上原本看得到的東西：設定摘要、連線狀態、啟用開關與動作。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Camera, ChevronDown, ChevronRight, Eye, Pencil, Trash2, Upload } from 'lucide-react'
import type { ReactNode } from 'react'

import { Badge, Card, IconButton, Switch } from '@/components/ui'
import { sourcePreviewUrl } from '@/lib/api'
import { summarizeSourceConfig } from '@/lib/sources'
import type { ImageSource } from '@/lib/types'

//: 種類的顯示順序：現場最常用的相機在最前面，合成產生器最後
const KIND_ORDER = ['capture', 'folder', 'file', 'upload', 'synthetic']

export interface SourceNode {
  kind: string
  total: number
  groups: { group: string; items: ImageSource[] }[]
}

/** 純函式：來源清單 → 種類／群組兩層（種類照 KIND_ORDER，群組照名稱，未分組排最後）。 */
export function buildSourceTree(items: ImageSource[]): SourceNode[] {
  const byKind = new Map<string, Map<string, ImageSource[]>>()
  for (const source of items) {
    const groups = byKind.get(source.kind) ?? new Map<string, ImageSource[]>()
    const key = source.group || ''
    groups.set(key, [...(groups.get(key) ?? []), source])
    byKind.set(source.kind, groups)
  }
  const rank = (kind: string) => (KIND_ORDER.indexOf(kind) < 0 ? KIND_ORDER.length : KIND_ORDER.indexOf(kind))
  return [...byKind.entries()]
    .sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]))
    .map(([kind, groups]) => {
      const rows = [...groups.entries()]
        .sort((a, b) => (a[0] === '' ? 1 : b[0] === '' ? -1 : a[0].localeCompare(b[0])))
        .map(([group, list]) => ({ group, items: [...list].sort((x, y) => x.name.localeCompare(y.name)) }))
      return { kind, groups: rows, total: rows.reduce((n, g) => n + g.items.length, 0) }
    })
}

export interface SourceViewProps {
  items: ImageSource[]
  kindLabel: (kind: string) => string
  status: (source: ImageSource) => ReactNode
  onPreview: (source: ImageSource) => void
  onEdit: (source: ImageSource) => void
  onDelete: (source: ImageSource) => void
  onToggle: (source: ImageSource, enabled: boolean) => void
  onPush: (source: ImageSource, file: File | undefined) => void
}

function Actions({ source, onPreview, onEdit, onDelete, onPush }: Pick<SourceViewProps, 'onPreview' | 'onEdit' | 'onDelete' | 'onPush'> & { source: ImageSource }) {
  const { t } = useTranslation()
  return (
    <span className="inline-flex shrink-0 items-center justify-end gap-1">
      {source.kind === 'upload' ? (
        <label className="btn-icon cursor-pointer" title={t('common.upload')}>
          <Upload size={15} />
          <input type="file" accept="image/*" className="hidden" onChange={(e) => onPush(source, e.target.files?.[0])} />
        </label>
      ) : null}
      <IconButton label={t('sources.preview')} onClick={() => onPreview(source)}><Eye size={15} /></IconButton>
      <IconButton label={t('common.edit')} onClick={() => onEdit(source)}><Pencil size={15} /></IconButton>
      <span className="mx-0.5 h-4 w-px bg-line" aria-hidden />
      <IconButton label={t('common.delete')} onClick={() => onDelete(source)} className="hover:!bg-critical-soft hover:!text-critical"><Trash2 size={15} /></IconButton>
    </span>
  )
}

export function SourceTree({ items, kindLabel, status, onPreview, onEdit, onDelete, onToggle, onPush }: SourceViewProps) {
  const { t } = useTranslation()
  const tree = useMemo(() => buildSourceTree(items), [items])
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const toggle = (key: string) => setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }))

  return (
    <div className="card divide-y divide-line" data-testid="source-tree">
      {tree.map((node) => {
        const kindKey = `k:${node.kind}`
        const kindOpen = !collapsed[kindKey]
        return (
          <section key={node.kind}>
            <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface-muted" onClick={() => toggle(kindKey)}
              data-testid={`source-kind-${node.kind}`} aria-expanded={kindOpen}>
              {kindOpen ? <ChevronDown size={14} className="text-muted" /> : <ChevronRight size={14} className="text-muted" />}
              <Camera size={14} className="text-muted" />
              <span className="text-sm font-medium">{kindLabel(node.kind)}</span>
              <span className="tnum text-xs text-muted">{node.total}</span>
            </button>
            {kindOpen ? node.groups.map((group) => {
              const groupKey = `g:${node.kind}:${group.group}`
              const groupOpen = !collapsed[groupKey]
              return (
                <div key={groupKey}>
                  <button type="button" className="flex w-full items-center gap-2 py-1.5 pl-8 pr-3 text-left hover:bg-surface-muted" onClick={() => toggle(groupKey)} aria-expanded={groupOpen}>
                    {groupOpen ? <ChevronDown size={12} className="text-subtle" /> : <ChevronRight size={12} className="text-subtle" />}
                    <span className="text-xs text-muted">{group.group || t('common.ungrouped')}</span>
                    <span className="tnum text-[11px] text-subtle">{group.items.length}</span>
                  </button>
                  {groupOpen ? group.items.map((source) => (
                    <div key={source.id} className="flex items-center gap-2 py-1 pl-14 pr-2 hover:bg-surface-muted" data-testid="source-row">
                      <span className="min-w-0 flex-1 truncate text-sm" title={source.name}>
                        {source.name} <span className="text-xs text-muted">#{source.id}</span>
                      </span>
                      <span className="min-w-0 max-w-[16rem] flex-1 truncate text-xs text-muted max-xl:hidden" title={JSON.stringify(source.config)}>
                        {summarizeSourceConfig(source.kind, source.config)}
                      </span>
                      <span className="shrink-0">{status(source)}</span>
                      <Switch checked={source.is_enabled} label={t('common.enabled')} onChange={(v) => onToggle(source, v)} />
                      <Actions source={source} onPreview={onPreview} onEdit={onEdit} onDelete={onDelete} onPush={onPush} />
                    </div>
                  )) : null}
                </div>
              )
            }) : null}
          </section>
        )
      })}
    </div>
  )
}

export function SourceCards({ items, kindLabel, status, onPreview, onEdit, onDelete, onToggle, onPush }: SourceViewProps) {
  const { t } = useTranslation()
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="source-cards">
      {items.map((source) => (
        <Card key={source.id} className="overflow-hidden" testId="source-card">
          <button type="button" className="block w-full bg-viewer" onClick={() => onPreview(source)} title={t('sources.preview')}>
            <img src={sourcePreviewUrl(source.id, 320)} alt="" className="aspect-[4/3] w-full object-contain" loading="lazy"
              onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
          </button>
          <div className="space-y-1.5 p-2.5">
            <p className="truncate text-sm font-medium" title={source.name}>{source.name} <span className="text-xs text-muted">#{source.id}</span></p>
            <div className="flex flex-wrap items-center gap-1.5 text-xs">
              <Badge tone="info">{kindLabel(source.kind)}</Badge>
              {source.group ? <Badge>{source.group}</Badge> : null}
              {status(source)}
            </div>
            <p className="truncate text-[11px] text-muted" title={JSON.stringify(source.config)}>{summarizeSourceConfig(source.kind, source.config)}</p>
            <div className="flex items-center justify-between">
              <Switch checked={source.is_enabled} label={t('common.enabled')} onChange={(v) => onToggle(source, v)} />
              <Actions source={source} onPreview={onPreview} onEdit={onEdit} onDelete={onDelete} onPush={onPush} />
            </div>
          </div>
        </Card>
      ))}
    </div>
  )
}
