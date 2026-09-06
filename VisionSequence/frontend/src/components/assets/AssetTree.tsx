/** 資產樹狀表：種類當父層、群組當子層、資產是葉節點（縮圖＋大小＋動作）。
 * 卡片檢視適合看圖，樹狀適合「這個站台到底有哪些東西」——尤其模型與檔案沒有縮圖可看。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, ChevronRight, FileBox, Images, Pencil, Trash2 } from 'lucide-react'

import { Badge } from '@/components/ui'
import { assetUrl } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import type { Asset } from '@/lib/types'

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

const KIND_ORDER = ['image', 'model', 'file', 'calibration', 'dataset']

function kindRank(kind: string): number {
  const i = KIND_ORDER.indexOf(kind)
  return i < 0 ? KIND_ORDER.length : i
}

export interface AssetNode {
  kind: string
  total: number
  bytes: number
  groups: { group: string; items: Asset[]; bytes: number }[]
}

/** 純函式：資產清單 → 種類／群組兩層（種類照 KIND_ORDER，群組照名稱，未分組排最後）。 */
export function buildTree(items: Asset[]): AssetNode[] {
  const byKind = new Map<string, Map<string, Asset[]>>()
  for (const asset of items) {
    const groups = byKind.get(asset.kind) ?? new Map<string, Asset[]>()
    const key = asset.group || ''
    groups.set(key, [...(groups.get(key) ?? []), asset])
    byKind.set(asset.kind, groups)
  }
  return [...byKind.entries()]
    .sort((a, b) => kindRank(a[0]) - kindRank(b[0]) || a[0].localeCompare(b[0]))
    .map(([kind, groups]) => {
      const rows = [...groups.entries()]
        .sort((a, b) => (a[0] === '' ? 1 : b[0] === '' ? -1 : a[0].localeCompare(b[0])))
        .map(([group, list]) => ({
          group,
          items: [...list].sort((x, y) => x.name.localeCompare(y.name)),
          bytes: list.reduce((sum, a) => sum + a.size, 0),
        }))
      return { kind, groups: rows, total: rows.reduce((n, g) => n + g.items.length, 0), bytes: rows.reduce((n, g) => n + g.bytes, 0) }
    })
}

export function AssetTree({ items, onEdit, onDelete }: { items: Asset[]; onEdit: (asset: Asset) => void; onDelete: (asset: Asset) => void }) {
  const { t } = useTranslation()
  const tree = useMemo(() => buildTree(items), [items])
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const toggle = (key: string) => setCollapsed((prev) => ({ ...prev, [key]: !prev[key] }))

  return (
    <div className="card divide-y divide-line" data-testid="asset-tree">
      {tree.map((node) => {
        const kindKey = `k:${node.kind}`
        const kindOpen = !collapsed[kindKey]
        return (
          <section key={node.kind}>
            <button type="button" className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface-muted" onClick={() => toggle(kindKey)}
              data-testid={`asset-kind-${node.kind}`} aria-expanded={kindOpen}>
              {kindOpen ? <ChevronDown size={14} className="text-muted" /> : <ChevronRight size={14} className="text-muted" />}
              {node.kind === 'image' ? <Images size={14} className="text-muted" /> : <FileBox size={14} className="text-muted" />}
              <span className="text-sm font-medium">{t(`assets.kinds.${node.kind}`, { defaultValue: node.kind })}</span>
              <span className="tnum text-xs text-muted">{node.total} · {formatSize(node.bytes)}</span>
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
                  {groupOpen ? group.items.map((asset) => (
                    <div key={asset.id} className="group flex items-center gap-2 py-1 pl-14 pr-2 hover:bg-surface-muted" data-testid="asset-row">
                      {asset.kind === 'image' ? (
                        <img src={assetUrl(asset.id, 64)} alt="" className="size-7 shrink-0 rounded border border-line object-cover" loading="lazy" />
                      ) : (
                        <FileBox size={16} className="size-7 shrink-0 p-1 text-subtle" />
                      )}
                      <span className="min-w-0 flex-1 truncate text-sm" title={asset.name}>{asset.name}</span>
                      <Badge tone={asset.kind === 'image' ? 'info' : asset.kind === 'model' ? 'brand' : 'neutral'}>{t(`assets.kinds.${asset.kind}`, { defaultValue: asset.kind })}</Badge>
                      <span className="tnum w-20 shrink-0 text-right text-xs text-muted">{formatSize(asset.size)}</span>
                      <span className="w-32 shrink-0 whitespace-nowrap text-right text-xs text-subtle max-lg:hidden">{asset.created_at ? formatDateTime(asset.created_at) : ''}</span>
                      <span className="flex shrink-0">
                        <button type="button" className="btn-icon" title={t('assets.editGroup')} onClick={() => onEdit(asset)}><Pencil size={13} /></button>
                        <button type="button" className="btn-icon" title={t('common.delete')} onClick={() => onDelete(asset)}><Trash2 size={13} className="text-critical" /></button>
                      </span>
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
