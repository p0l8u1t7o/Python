/** 邊：依來源埠型別上色；上一 run 有資料流過（來源節點 ok）時加一顆沿線移動的小點。 */
import { BaseEdge, getBezierPath, type EdgeProps } from '@xyflow/react'
import { memo } from 'react'

import { portColor } from '@/lib/ports'

function FlowEdgeInner({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, style, markerEnd, data, selected }: EdgeProps) {
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition })
  const portType = (data as { portType?: string } | undefined)?.portType
  const flowing = Boolean((data as { flowing?: boolean } | undefined)?.flowing)
  const color = portType === 'note' ? 'var(--warning)' : portColor(portType)
  return (
    <>
      <BaseEdge id={id} path={path} markerEnd={markerEnd} style={{ ...style, stroke: selected ? 'var(--brand)' : color, strokeWidth: selected ? 2.4 : 1.8, opacity: flowing ? 1 : 0.75 }} />
      {flowing ? (
        <circle r={3.5} fill={color} stroke="var(--surface)" strokeWidth={1.2}>
          <animateMotion dur="1.4s" repeatCount="indefinite" path={path} />
        </circle>
      ) : null}
    </>
  )
}

export const FlowEdge = memo(FlowEdgeInner)
