/**
 * 畫布上的工具卡片：左側輸入埠、右側輸出埠、左上角控制輸入菱形（_flow）。
 * 執行狀態：ok 綠點、ng 橘點、error 紅框、skipped 淡化、running 旋轉光環。
 *
 * 埠的顯示依 lib/portLayout.ts（PRODUCT-DIRECTION v2 §2）：已接線／primary／已發布／必填未接／使用者勾選的才畫，
 * 其餘收合成下緣的「＋N」徽章，點一下就地展開（只在這次檢視，不寫進 graph）；被藏起來的必填未接輸入另掛紅色徽章。
 * 把手集合變了要通知 React Flow 重量（updateNodeInternals），不然接到新露出把手的線會靜默不畫。
 */
import { Handle, NodeResizer, Position, useEdges, useUpdateNodeInternals, type NodeProps } from '@xyflow/react'
import * as icons from 'lucide-react'
import { memo, useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { FLOW_HANDLE, portColor } from '@/lib/ports'
import { outputAliases } from '@/lib/nodeInterface'
import { connectedHandles, portLayout } from '@/lib/portLayout'
import type { GraphEdge, ToolPort } from '@/lib/types'
import type { ToolNodeData } from './graphMapping'

export function iconFor(name: string | undefined): icons.LucideIcon {
  return (name && (icons as unknown as Record<string, icons.LucideIcon>)[name]) || icons.Box
}

/** 黑或近白，看哪個在 hex 上讀得清楚。 */
export function contrastText(hex: string): string {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!match) return ''
  const value = parseInt(match[1], 16)
  const r = value >> 16
  const g = (value >> 8) & 255
  const b = value & 255
  return (r * 299 + g * 587 + b * 114) / 1000 >= 145 ? '#0f172a' : '#f8fafc'
}

const TONE_COLOR: Record<ToolPort['tone'], string> = {
  neutral: 'var(--port-flow)',
  ok: 'var(--ok)',
  warn: 'var(--warning)',
  critical: 'var(--critical)',
}

function PortRow({ port, side, customFg, publishName, publishTitle, dim }: { port: ToolPort; side: 'in' | 'out'; customFg: string; publishName?: string; publishTitle?: string; dim?: boolean }) {
  const isFlow = port.type === 'flow'
  const color = isFlow ? TONE_COLOR[port.tone] : portColor(port.type)
  // 隱含輸出埠（_overlays）：較小較淡，免得跟真正的資料輸出搶注意力。
  const implicit = port.implicit === true
  return (
    <div className={`relative flex items-center ${implicit ? 'h-4 opacity-60' : 'h-5'} ${dim ? 'opacity-70' : ''} ${side === 'in' ? 'pl-3' : 'justify-end pr-3'}`} data-port={`${side}:${port.key}`}>
      <span className={`truncate leading-none ${implicit ? 'text-[9px]' : 'text-[10px]'} ${customFg ? 'opacity-80' : 'text-muted'}`} title={`${port.label} (${port.type})`}>
        {port.label}
        {port.required && side === 'in' ? <span className="text-critical">*</span> : null}
      </span>
      {side === 'out' && publishName ? (
        <span className="ml-1 max-w-20 truncate rounded border border-brand/40 bg-brand-soft px-1 py-px font-mono text-[9px] leading-none text-brand" title={publishTitle}>
          {publishName}
        </span>
      ) : null}
      <Handle
        id={port.key}
        type={side === 'in' ? 'target' : 'source'}
        position={side === 'in' ? Position.Left : Position.Right}
        className={`${implicit ? '!size-2' : '!size-2.5'} !border-2 ${isFlow ? '!rounded-none !rotate-45' : '!rounded-full'}`}
        style={{ background: color, borderColor: 'var(--surface)' }}
        title={`${port.key}: ${port.type}`}
      />
    </div>
  )
}

/** 只留這個節點的邊（其餘節點的邊變動不該讓每張卡片重算）。 */
function useNodeEdges(nodeId: string): GraphEdge[] {
  const edges = useEdges()
  return useMemo(
    () =>
      edges
        .filter((edge) => edge.source === nodeId || edge.target === nodeId)
        .map((edge) => ({ id: edge.id, source: edge.source, target: edge.target, source_handle: edge.sourceHandle ?? undefined, target_handle: edge.targetHandle ?? undefined })),
    [edges, nodeId],
  )
}

function ToolNodeInner({ id, data, selected }: NodeProps) {
  const { t } = useTranslation()
  const node = data as ToolNodeData
  const def = node.definition
  const Icon = iconFor(def?.icon)
  const report = node.report
  const customBg = node.color && contrastText(node.color) ? node.color : ''
  const fg = customBg ? contrastText(customBg) : ''
  const status = report?.status

  const border = selected
    ? 'border-brand ring-2 ring-brand/35 shadow-lg shadow-brand/10'
    : status === 'error'
      ? 'border-critical ring-2 ring-critical/30'
      : node.problem
        ? 'border-critical'
        : customBg
          ? 'border-transparent'
          : 'border-line'
  const dot = status === 'ok' ? 'bg-ok' : status === 'ng' ? 'bg-warning' : status === 'error' ? 'bg-critical' : status === 'skipped' ? 'bg-line-strong' : ''

  // ---- 埠：依規則收合，「＋N」就地展開 ----
  const nodeEdges = useNodeEdges(id)
  const [expanded, setExpanded] = useState(false)
  const layoutIn = useMemo(() => portLayout(def, node, 'in', connectedHandles(id, nodeEdges, 'in')), [def, node, id, nodeEdges])
  const layoutOut = useMemo(() => portLayout(def, node, 'out', connectedHandles(id, nodeEdges, 'out')), [def, node, id, nodeEdges])
  const inputs = expanded ? layoutIn.all.map((view) => view.port) : layoutIn.visible
  const outputs = expanded ? layoutOut.all.map((view) => view.port) : layoutOut.visible
  const hiddenIn = new Set(layoutIn.hidden.map((port) => port.key))
  const hiddenOut = new Set(layoutOut.hidden.map((port) => port.key))
  const hiddenCount = layoutIn.hidden.length + layoutOut.hidden.length
  const hiddenProblems = layoutIn.hiddenProblems
  const rows = Math.max(inputs.length, outputs.length)
  const published = outputAliases(node)

  // 把手集合變了（展開／收合、接線露出埠、改了 interface）就請 React Flow 重量把手位置。
  const updateNodeInternals = useUpdateNodeInternals()
  const handleSignature = [...inputs.map((port) => `i:${port.key}`), ...outputs.map((port) => `o:${port.key}`)].join('|')
  useEffect(() => {
    updateNodeInternals(id)
  }, [handleSignature, id, updateNodeInternals])

  const moreTitle = expanded
    ? t('editor.ports.collapse')
    : hiddenProblems.length
      ? t('editor.ports.problemBadge', { count: hiddenProblems.length, labels: hiddenProblems.map((port) => port.label).join(', ') })
      : t('editor.ports.moreTitle', { count: hiddenCount })

  return (
    <div
      className={`relative min-w-[200px] max-w-[260px] rounded-lg border-2 shadow-sm transition
        ${customBg ? '' : 'bg-surface'} ${border}
        ${!node.enabled ? 'border-dashed opacity-55' : ''}
        ${status === 'skipped' ? 'opacity-60' : ''}
        ${node.running ? 'vs-node-loading' : ''}`}
      style={customBg ? { background: customBg, color: fg } : undefined}
    >
      {/* 控制輸入：左上角菱形。每個可執行節點都有，flow 分支只能接這裡。 */}
      <Handle
        id={FLOW_HANDLE}
        type="target"
        position={Position.Left}
        className="!left-0 !top-3 !size-2.5 !-translate-x-1/2 !rotate-45 !rounded-none !border-2"
        style={{ background: 'var(--port-flow)', borderColor: 'var(--surface)' }}
        title={t('editor.flowHandle')}
      />
      <div className="flex items-start gap-2 px-3 pt-2">
        <span className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md ${customBg ? '' : 'bg-brand-soft text-brand'}`} style={customBg ? { background: 'rgb(255 255 255 / 0.18)', color: fg } : undefined}>
          <Icon size={14} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium leading-tight">{node.label || def?.label || t('editor.unknownTool')}</p>
          <p className={`truncate text-[10px] ${customBg ? 'opacity-75' : 'text-muted'}`}>
            {def?.label ?? '?'}
            {def?.heavy ? ` · ${t('editor.heavy')}` : ''}
          </p>
        </div>
        {dot ? <span className={`mt-1 size-2.5 shrink-0 rounded-full ${dot}`} title={status} /> : null}
        {!node.enabled ? <icons.PowerOff size={12} className="mt-1 shrink-0 opacity-70" aria-hidden /> : null}
        {node.outdated ? <span className="mt-1 shrink-0 rounded bg-warning-soft px-1 text-[9px] font-semibold text-warning" title={t('editor.composite.versionBadge', { from: node.outdated.pinned, to: node.outdated.current })} data-testid="node-tool-outdated">v{node.outdated.pinned}</span> : null}
      </div>
      {node.problem ? <p className="px-3 pt-1 text-[10px] text-critical">{node.problem}</p> : null}
      {report?.message && status !== 'ok' ? (
        <p className={`truncate px-3 pt-1 text-[10px] ${status === 'error' ? 'text-critical font-medium' : 'text-warning'}`} title={report.message} data-testid={status === 'error' ? 'node-error' : undefined}>
          {report.message.split('\n')[0]}
        </p>
      ) : null}

      {rows > 0 ? (
        <div className="mt-1.5 grid grid-cols-2 pb-1.5">
          <div>
            {inputs.map((port) => (
              <PortRow key={port.key} port={port} side="in" customFg={fg} dim={hiddenIn.has(port.key)} />
            ))}
          </div>
          <div>
            {outputs.map((port) => (
              <PortRow key={port.key} port={port} side="out" customFg={fg} dim={hiddenOut.has(port.key)} publishName={published[port.key]} publishTitle={published[port.key] ? t('editor.publishedOutputs.nodeHint', { name: published[port.key] }) : undefined} />
            ))}
          </div>
        </div>
      ) : (
        <div className="pb-2" />
      )}
      {hiddenCount > 0 || expanded ? (
        <div className="flex justify-center pb-1.5">
          <button
            type="button"
            className={`nodrag inline-flex h-4 min-w-7 items-center justify-center gap-0.5 rounded-full border px-1.5 text-[9px] font-medium leading-none ${
              hiddenProblems.length && !expanded
                ? 'border-critical/50 bg-critical-soft text-critical'
                : customBg
                  ? 'border-current/40 bg-transparent opacity-80'
                  : 'border-line bg-surface-muted text-muted hover:text-content'
            }`}
            title={moreTitle}
            aria-label={moreTitle}
            data-testid="node-ports-more"
            data-hidden-count={hiddenCount}
            data-hidden-problems={hiddenProblems.length}
            onClick={(event) => {
              event.stopPropagation()
              setExpanded((value) => !value)
            }}
          >
            {expanded ? <icons.ChevronUp size={9} aria-hidden /> : hiddenProblems.length ? <icons.AlertTriangle size={9} aria-hidden /> : null}
            {expanded ? t('editor.ports.collapse') : t('editor.ports.more', { count: hiddenCount })}
          </button>
        </div>
      ) : null}
      {report ? (
        // 獨立一列（不用 absolute）：疊在角落會壓到最後一個輸出埠的名稱。
        // 耗時依「佔該次最慢節點的比例」著色：最慢的紅、一半以上橙，瓶頸一眼看得到。
        <div className="px-3 pb-1" data-testid="node-timing" data-heat={heatLevel(node.heat)}>
          <div className="h-0.5 w-full overflow-hidden rounded bg-line/60">
            <div className={`h-full ${heatLevel(node.heat) === 'hot' ? 'bg-critical' : heatLevel(node.heat) === 'warm' ? 'bg-warning' : 'bg-ok/60'}`} style={{ width: `${Math.round(Math.max(0.04, node.heat ?? 0) * 100)}%` }} />
          </div>
          <p className={`text-right text-[9px] leading-none tabular-nums ${heatLevel(node.heat) === 'hot' ? 'font-semibold text-critical' : heatLevel(node.heat) === 'warm' ? 'text-warning' : customBg ? 'opacity-70' : 'text-subtle'}`}>
            {report.duration_ms >= 10 ? Math.round(report.duration_ms) : report.duration_ms.toFixed(1)} ms
          </p>
        </div>
      ) : null}
    </div>
  )
}

/** 0.85 以上＝該次最慢的那幾步（hot）、0.5 以上＝值得看一眼（warm）。 */
export function heatLevel(heat: number | undefined): 'hot' | 'warm' | 'cool' {
  if (heat === undefined || heat <= 0) return 'cool'
  return heat >= 0.85 ? 'hot' : heat >= 0.5 ? 'warm' : 'cool'
}

export const ToolNode = memo(ToolNodeInner)

function NoteNodeInner({ data, selected }: NodeProps) {
  const node = data as ToolNodeData
  const customBg = node.color && contrastText(node.color) ? node.color : ''
  const fg = customBg ? contrastText(customBg) : ''
  return (
    <div
      className={`h-full min-h-[60px] w-full min-w-[160px] rounded-md border p-3 shadow-sm ${customBg ? '' : 'bg-warning-soft'} ${selected ? 'border-brand ring-2 ring-brand/35' : customBg ? 'border-transparent' : 'border-warning/40'}`}
      style={customBg ? { background: customBg, color: fg } : undefined}
    >
      <NodeResizer isVisible={selected} minWidth={160} minHeight={60} maxWidth={640} maxHeight={480} />
      <div className="flex h-full items-start gap-2">
        <icons.StickyNote size={14} aria-hidden className={`mt-0.5 shrink-0 ${customBg ? 'opacity-80' : 'text-warning'}`} />
        <div className="min-w-0 flex-1 overflow-hidden">
          {node.label ? <p className="text-xs font-medium">{node.label}</p> : null}
          <p className="whitespace-pre-wrap text-[11px] leading-snug opacity-85">{node.description || String(node.params?.text ?? '')}</p>
        </div>
      </div>
    </div>
  )
}

export const NoteNode = memo(NoteNodeInner)
