import { BaseEdge, getBezierPath, type EdgeProps } from '@xyflow/react'

/**
 * The standard edge, plus a dot that travels the path while data flows.
 *
 * The Animated-SVG-Edge pattern: a `<circle>` rides the edge path with
 * `<animateMotion>`, so during a run the taken route reads as *moving* -
 * which is what "the token went this way" actually means - instead of every
 * edge pulsing its dash pattern identically whether anything travels it or
 * not. `data.flowing` is set by the editor on edges entering a node a live
 * branch is sitting on.
 */
export function AnimatedFlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  markerEnd,
  data,
}: EdgeProps) {
  const [path] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  })

  return (
    <>
      <BaseEdge id={id} path={path} style={style} markerEnd={markerEnd} />
      {data?.flowing ? (
        <circle r={4} fill="var(--brand)" stroke="var(--surface)" strokeWidth={1.5}>
          <animateMotion dur="1.1s" repeatCount="indefinite" path={path} />
        </circle>
      ) : null}
    </>
  )
}
