import { Handle, Position, type NodeProps } from '@xyflow/react'
import { Boxes } from 'lucide-react'
import { memo } from 'react'
import { useTranslation } from 'react-i18next'

import type { GroupNodeData } from '@/lib/nodeGroups'

const STATUS_RANK: Record<string, number> = { ok: 1, skipped: 2, ng: 3, error: 4, failed: 4 }

function worstStatus(data: GroupNodeData): string | null {
  let worst: string | null = null
  let rank = 0
  for (const id of data.group.node_ids) {
    const status = data.reports?.[id]?.status
    const next = status ? STATUS_RANK[status] ?? 0 : 0
    if (next > rank) {
      rank = next
      worst = status ?? null
    }
  }
  return worst
}

function statusClass(status: string | null): string {
  if (status === 'ok') return 'bg-ok'
  if (status === 'ng') return 'bg-warning'
  if (status === 'error' || status === 'failed') return 'bg-critical'
  if (status === 'skipped') return 'bg-line-strong'
  return 'bg-line'
}

function GroupNodeInner({ data, selected }: NodeProps) {
  const { t } = useTranslation()
  const group = data as GroupNodeData
  const status = worstStatus(group)
  const row = (handles: string[], type: 'target' | 'source') =>
    handles.map((handle, index) => (
      <Handle
        key={handle}
        id={handle}
        type={type}
        position={type === 'target' ? Position.Left : Position.Right}
        className="!size-2.5 !border-2 !border-surface !bg-brand"
        style={{ top: `${((index + 1) / (handles.length + 1)) * 100}%` }}
        isConnectable={false}
      />
    ))

  return (
    <div
      className={`relative w-[220px] rounded-lg border-2 bg-surface px-3 py-2 shadow-sm ${selected ? 'border-brand ring-2 ring-brand/35 shadow-lg shadow-brand/10' : 'border-line'}`}
      data-testid="group-node"
      onDoubleClick={(event) => {
        event.stopPropagation()
        group.onExpand?.(group.group.task_id)
      }}
    >
      {row(group.inputHandles, 'target')}
      {row(group.outputHandles, 'source')}
      <div className="flex items-start gap-2">
        <span className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md bg-brand-soft text-brand">
          <Boxes size={15} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold leading-tight">{group.group.label}</p>
          <p className="truncate text-[10px] text-muted">{t('editor.groups.memberCount', { count: group.group.node_ids.length })}</p>
        </div>
        <span className={`mt-1 size-2.5 shrink-0 rounded-full ${statusClass(status)}`} title={status ?? undefined} data-testid="group-status" />
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[10px] text-subtle">{group.group.task_id}</span>
        <button type="button" className="rounded px-1.5 py-0.5 text-[11px] text-brand hover:bg-brand-soft" onClick={() => group.onExpand?.(group.group.task_id)} data-testid="group-expand">
          {t('editor.groups.expand')}
        </button>
      </div>
    </div>
  )
}

export const GroupNode = memo(GroupNodeInner)
