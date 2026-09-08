import type { GraphEdge } from '@/lib/types'

export interface SpanTimingNode {
  duration_ms?: number | null
}

export interface SpanTimingResult {
  source: string
  target: string
  hasPath: boolean
  totalMs: number
  nodeCount: number
  percent: number
  nodeIds: string[]
  nodes: { id: string; durationMs: number }[]
}

function durationOf(node: SpanTimingNode | undefined): number {
  const value = Number(node?.duration_ms ?? 0)
  return Number.isFinite(value) && value > 0 ? value : 0
}

/** 計算資料流路徑上來源至目的節點的耗時聯集。 */
export function calculateSpanTiming(
  nodes: Record<string, SpanTimingNode | undefined>,
  edges: Pick<GraphEdge, 'source' | 'target'>[],
  source: string,
  target: string,
): SpanTimingResult {
  const allTotal = Object.values(nodes).reduce((sum, node) => sum + durationOf(node), 0)
  const empty = (hasPath: boolean): SpanTimingResult => ({
    source,
    target,
    hasPath,
    totalMs: 0,
    nodeCount: 0,
    percent: 0,
    nodeIds: [],
    nodes: [],
  })

  if (!source || !target || !nodes[source] || !nodes[target]) return empty(false)
  if (source === target) {
    const durationMs = durationOf(nodes[source])
    return {
      source,
      target,
      hasPath: true,
      totalMs: durationMs,
      nodeCount: 1,
      percent: allTotal > 0 ? (durationMs / allTotal) * 100 : 0,
      nodeIds: [source],
      nodes: [{ id: source, durationMs }],
    }
  }

  const next = new Map<string, string[]>()
  for (const edge of edges) {
    if (!nodes[edge.source] || !nodes[edge.target]) continue
    const list = next.get(edge.source) ?? []
    list.push(edge.target)
    next.set(edge.source, list)
  }

  const inSpan = new Set<string>()
  const visit = (id: string, path: string[]): boolean => {
    if (path.includes(id)) return false
    const nextPath = [...path, id]
    if (id === target) {
      for (const item of nextPath) inSpan.add(item)
      return true
    }
    let found = false
    for (const child of next.get(id) ?? []) {
      if (visit(child, nextPath)) found = true
    }
    if (found) for (const item of nextPath) inSpan.add(item)
    return found
  }

  if (!visit(source, [])) return empty(false)
  const nodeIds = Object.keys(nodes).filter((id) => inSpan.has(id))
  const spanNodes = nodeIds.map((id) => ({ id, durationMs: durationOf(nodes[id]) }))
  const totalMs = spanNodes.reduce((sum, node) => sum + node.durationMs, 0)
  return {
    source,
    target,
    hasPath: true,
    totalMs,
    nodeCount: spanNodes.length,
    percent: allTotal > 0 ? (totalMs / allTotal) * 100 : 0,
    nodeIds,
    nodes: spanNodes,
  }
}
