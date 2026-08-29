/** 步驟清單（NodeList）：左欄下半，本流程所有步驟；點一下選取並把畫布聚焦到該步驟。 */
import { useTranslation } from 'react-i18next'

import type { GraphNode, ToolTypeDef } from '@/lib/types'
import { iconFor } from './ToolNode'

export function NodeList({ nodes, defs, selectedId, statuses, onSelect }: { nodes: GraphNode[]; defs: Map<string, ToolTypeDef>; selectedId: string | null; statuses: Map<string, string>; onSelect: (id: string) => void }) {
  const { t } = useTranslation()
  if (nodes.length === 0) return <p className="px-3 py-2 text-xs text-muted">{t('editor.noNodes')}</p>
  return (
    <div className="h-full overflow-y-auto px-2 pb-2" data-testid="node-list">
      {nodes.map((node) => {
        const def = defs.get(node.type)
        const Icon = iconFor(def?.icon)
        const status = statuses.get(node.id)
        const dot = status === 'ok' ? 'bg-ok' : status === 'ng' ? 'bg-warning' : status === 'error' ? 'bg-critical' : 'bg-line-strong'
        return (
          <button key={node.id} type="button" data-node-id={node.id} onClick={() => onSelect(node.id)} className={`flex w-full items-center gap-2 rounded px-2 py-1 text-left text-xs ${selectedId === node.id ? 'bg-brand-soft text-brand' : 'hover:bg-surface-muted'} ${node.enabled === false ? 'opacity-50' : ''}`}>
            <span className={`size-1.5 shrink-0 rounded-full ${dot}`} />
            <Icon size={13} className="shrink-0" aria-hidden />
            <span className="truncate">{node.label || def?.label || node.type}</span>
            <span className="ml-auto truncate font-mono text-[10px] text-subtle">{node.id}</span>
          </button>
        )
      })}
    </div>
  )
}
