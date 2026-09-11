/** 邊：依來源埠型別上色；上一 run 有資料流過（來源節點 ok）時加一顆沿線移動的小點，並可把來源埠的值標在線上。 */
import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react'
import { memo } from 'react'

import { portColor } from '@/lib/ports'

const MAX_LABEL = 24

/** 試跑報告裡的輸出值 → 線上的短標籤；影像等物件不標（回 undefined）。 */
export function formatEdgeValue(value: unknown): string | undefined {
  if (value === null || value === undefined) return undefined
  if (typeof value === 'number') return Number.isFinite(value) ? String(Number(value.toFixed(3))) : String(value)
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (typeof value === 'string') {
    const text = value.replace(/\s+/g, ' ').trim()
    if (!text) return undefined
    return text.length > MAX_LABEL ? `${text.slice(0, MAX_LABEL - 1)}…` : text
  }
  if (Array.isArray(value)) return `[${value.length}]`
  if (typeof value === 'object') {
    // 影像參照 {ref, width, height} 與其他結構不標；區域只標形狀
    const record = value as Record<string, unknown>
    if ('ref' in record) return undefined
    if (typeof record.shape === 'string') return record.shape
    return undefined
  }
  return undefined
}

function FlowEdgeInner({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, data, selected }: EdgeProps) {
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const portType = (data as { portType?: string } | undefined)?.portType
  const flowing = Boolean((data as { flowing?: boolean } | undefined)?.flowing)
  const value = (data as { value?: string } | undefined)?.value
  const color = portType === 'note' ? 'var(--warning)' : portColor(portType)
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={{ ...style, stroke: selected ? 'var(--brand)' : color, strokeWidth: selected ? 2.4 : 1.8, opacity: flowing ? 1 : 0.75 }} />
      {flowing ? (
        <circle r={3.5} fill={color} stroke="var(--surface)" strokeWidth={1.2}>
          <animateMotion dur="1.4s" repeatCount="indefinite" path={path} />
        </circle>
      ) : null}
      {value !== undefined ? (
        <EdgeLabelRenderer>
          <div
            className="pointer-events-none absolute rounded border bg-surface/95 px-1 font-mono text-[10px] leading-4 text-heading shadow-sm"
            style={{ transform: `translate(-50%, -50%) translate(${labelX}px, ${labelY}px)`, borderColor: color }}
            data-testid="edge-value"
            title={value}
          >
            {value}
          </div>
        </EdgeLabelRenderer>
      ) : null}
    </>
  )
}

export const FlowEdge = memo(FlowEdgeInner)
