import { checkConnection, DECORATION_TYPES } from '@/lib/graphValidation'
import type { FlowGraph, GraphNode, ToolPort, ToolTypeDef } from '@/lib/types'

export interface SourceCandidate {
  nodeId: string
  portKey: string
  nodeLabel: string
  portLabel: string
  portType: string
}

function downstreamReaches(graph: FlowGraph, from: string, to: string): boolean {
  if (from === to) return true
  const seen = new Set<string>()
  const stack = [from]
  while (stack.length) {
    const id = stack.pop() as string
    if (seen.has(id)) continue
    seen.add(id)
    for (const edge of graph.edges ?? []) {
      if (edge.source !== id) continue
      if (edge.target === to) return true
      stack.push(edge.target)
    }
  }
  return false
}

function semanticCompatible(source: ToolPort, target: ToolPort): boolean {
  const semantic = source.semantic
  const accepts = target.accepts_semantics ?? []
  if (!semantic || accepts.length === 0) return true
  return accepts.includes(semantic)
}

function candidateCheckEdges(graph: FlowGraph, targetNodeId: string, targetPort: ToolPort) {
  if (targetPort.multiple) return graph.edges ?? []
  return (graph.edges ?? []).filter((edge) => !(edge.target === targetNodeId && (edge.target_handle ?? '') === targetPort.key))
}

function candidateRank(target: GraphNode, source: GraphNode): number {
  const targetTask = target.meta?.inspect?.task_id
  const sourceInspect = source.meta?.inspect
  if (targetTask && sourceInspect?.task_id === targetTask) return 0
  if (sourceInspect?.kind === 'locate_part') return 1
  return 2
}

export function sourceCandidates(
  graph: FlowGraph,
  targetNodeId: string,
  targetPortKey: string,
  defs: Map<string, ToolTypeDef>,
): SourceCandidate[] {
  const nodes = graph.nodes ?? []
  const target = nodes.find((node) => node.id === targetNodeId)
  const targetDef = target ? defs.get(target.type) : undefined
  const targetPort = targetDef?.inputs.find((port) => port.key === targetPortKey)
  if (!target || !targetPort) return []

  const nodeMap = new Map(nodes.map((node) => [node.id, node]))
  const checkEdges = candidateCheckEdges(graph, targetNodeId, targetPort)
  const connected = new Set((graph.edges ?? [])
    .filter((edge) => edge.target === targetNodeId && (edge.target_handle ?? '') === targetPort.key)
    .map((edge) => `${edge.source}:${edge.source_handle ?? ''}`))
  const out: SourceCandidate[] = []

  for (const node of nodes) {
    if (node.id === targetNodeId || DECORATION_TYPES.has(node.type)) continue
    if (targetPort.multiple && connected.has(`${node.id}:`)) continue
    if (downstreamReaches(graph, targetNodeId, node.id)) continue
    const def = defs.get(node.type)
    for (const port of def?.outputs ?? []) {
      if (port.implicit === true || port.key === '_image' || port.key === '_overlays' || port.type === 'flow') continue
      if (targetPort.multiple && connected.has(`${node.id}:${port.key}`)) continue
      if (!semanticCompatible(port, targetPort)) continue
      const rejection = checkConnection(
        { source: node.id, sourceHandle: port.key, target: targetNodeId, targetHandle: targetPort.key },
        nodeMap,
        checkEdges,
        defs,
      )
      if (rejection) continue
      out.push({
        nodeId: node.id,
        portKey: port.key,
        nodeLabel: node.label || def?.label || node.id,
        portLabel: port.label || port.key,
        portType: port.type,
      })
    }
  }

  const order = new Map(nodes.map((node, index) => [node.id, index]))
  return out.sort((a, b) => {
    const aNode = nodeMap.get(a.nodeId)
    const bNode = nodeMap.get(b.nodeId)
    const rank = candidateRank(target, aNode ?? target) - candidateRank(target, bNode ?? target)
    if (rank !== 0) return rank
    return (order.get(a.nodeId) ?? 0) - (order.get(b.nodeId) ?? 0) || a.portKey.localeCompare(b.portKey)
  })
}
