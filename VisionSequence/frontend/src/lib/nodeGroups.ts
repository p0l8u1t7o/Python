import type { Edge, Node } from '@xyflow/react'

import { edgeProps } from '@/components/editor/graphMapping'
import type { FlowGraph, GraphEdge, GraphNode, NodeReport, ToolTypeDef } from './types'

export const GROUP_NODE_TYPE = 'group'
export const GROUP_NODE_WIDTH = 220
export const GROUP_NODE_HEIGHT = 92
export const GROUP_NODE_PREFIX = 'group:'
export const GROUP_HANDLE_PREFIX = 'member:'

export interface NodeGroup {
  task_id: string
  kind: string
  node_ids: string[]
  label: string
}

export interface GroupNodeData extends Record<string, unknown> {
  group: NodeGroup
  inputHandles: string[]
  outputHandles: string[]
  reports: Record<string, NodeReport> | null
  onExpand?: (taskId: string) => void
}

export interface CollapsedView {
  nodes: Node[]
  edges: Edge[]
}

const KIND_KEYS = new Set([
  'measure_diameter',
  'measure_distance',
  'locate_part',
  'count_objects',
  'check_presence',
  'inspect_circular_surface',
  'inspect_edge_defect',
  'read_and_verify',
])

function groupNodeId(taskId: string): string {
  return `${GROUP_NODE_PREFIX}${taskId}`
}

export function taskIdFromGroupNodeId(id: string): string | null {
  return id.startsWith(GROUP_NODE_PREFIX) ? id.slice(GROUP_NODE_PREFIX.length) : null
}

export function groupHandleId(nodeId: string, port: string | null | undefined): string {
  return `${GROUP_HANDLE_PREFIX}${encodeURIComponent(nodeId)}:${encodeURIComponent(port ?? '')}`
}

export function parseGroupHandleId(handle: string | null | undefined): { nodeId: string; port: string } | null {
  if (!handle?.startsWith(GROUP_HANDLE_PREFIX)) return null
  const body = handle.slice(GROUP_HANDLE_PREFIX.length)
  const split = body.indexOf(':')
  if (split < 0) return null
  return { nodeId: decodeURIComponent(body.slice(0, split)), port: decodeURIComponent(body.slice(split + 1)) }
}

export function taskKindLabel(kind: string, t: (key: string, fallback: string) => string): string {
  return KIND_KEYS.has(kind) ? t(`editor.groups.kinds.${kind}`, kind) : kind
}

export function groupsOf(graph: FlowGraph, _defs?: Map<string, ToolTypeDef>, t?: (key: string, fallback: string) => string): NodeGroup[] {
  const buckets = new Map<string, GraphNode[]>()
  for (const node of graph.nodes ?? []) {
    if (node.type === 'image_source' || node.type === 'fixed_image') continue
    const inspect = node.meta?.inspect
    if (!inspect?.task_id) continue
    const list = buckets.get(inspect.task_id)
    if (list) list.push(node)
    else buckets.set(inspect.task_id, [node])
  }
  return Array.from(buckets.entries()).map(([task_id, members]) => {
    const findNode = members.find((node) => node.meta?.inspect?.role === 'find')
    const first = findNode ?? members[0]
    const kind = first.meta?.inspect?.kind ?? ''
    const title = (findNode?.label ?? '').trim() || (members.find((node) => (node.label ?? '').trim())?.label ?? '').trim()
    const fallback = title || taskKindLabel(kind, t ?? ((_key, value) => value))
    const label = fallback || task_id
    return { task_id, kind, node_ids: members.map((node) => node.id), label }
  })
}

function boundsOf(members: Node[]): { x: number; y: number; w: number; h: number } {
  let minX = Number.POSITIVE_INFINITY
  let minY = Number.POSITIVE_INFINITY
  let maxX = Number.NEGATIVE_INFINITY
  let maxY = Number.NEGATIVE_INFINITY
  for (const node of members) {
    const w = node.width ?? GROUP_NODE_WIDTH
    const h = node.height ?? GROUP_NODE_HEIGHT
    minX = Math.min(minX, node.position.x)
    minY = Math.min(minY, node.position.y)
    maxX = Math.max(maxX, node.position.x + w)
    maxY = Math.max(maxY, node.position.y + h)
  }
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY }
}

function edgeKey(source: string, sourceHandle: string, target: string, targetHandle: string): string {
  return `${source}\u0000${sourceHandle}\u0000${target}\u0000${targetHandle}`
}

function edgeSourceType(edge: GraphEdge, payloads: Map<string, GraphNode>, defs?: Map<string, ToolTypeDef>): string {
  const source = payloads.get(edge.source)
  const def = source ? defs?.get(source.type) : undefined
  const handle = edge.source_handle || def?.outputs[0]?.key || ''
  return def?.outputs.find((port) => port.key === handle)?.type ?? (handle === '_image' ? 'image' : 'any')
}

export function collapseView(
  nodes: Node[],
  edges: Edge[],
  collapsed: Set<string>,
  graph: FlowGraph,
  defs?: Map<string, ToolTypeDef>,
  reports?: Record<string, NodeReport> | null,
  onExpand?: (taskId: string) => void,
): CollapsedView {
  if (!collapsed.size) return { nodes, edges }
  const payloads = new Map((graph.nodes ?? []).map((node) => [node.id, node]))
  const groups = groupsOf(graph, defs)
  const nodeToGroup = new Map<string, NodeGroup>()
  const inputHandles = new Map<string, Set<string>>()
  const outputHandles = new Map<string, Set<string>>()
  for (const group of groups) {
    if (!collapsed.has(group.task_id)) continue
    inputHandles.set(group.task_id, new Set())
    outputHandles.set(group.task_id, new Set())
    for (const id of group.node_ids) nodeToGroup.set(id, group)
  }
  if (!nodeToGroup.size) return { nodes, edges }
  for (const edge of graph.edges ?? []) {
    const sourceGroup = nodeToGroup.get(edge.source)
    const targetGroup = nodeToGroup.get(edge.target)
    if (sourceGroup && targetGroup && sourceGroup.task_id === targetGroup.task_id) continue
    if (targetGroup) inputHandles.get(targetGroup.task_id)?.add(groupHandleId(edge.target, edge.target_handle))
    if (sourceGroup) outputHandles.get(sourceGroup.task_id)?.add(groupHandleId(edge.source, edge.source_handle))
  }

  const nodesById = new Map(nodes.map((node) => [node.id, node]))
  const visibleNodes: Node[] = nodes.filter((node) => !nodeToGroup.has(node.id))
  for (const group of groups) {
    if (!collapsed.has(group.task_id)) continue
    const members = group.node_ids.map((id) => nodesById.get(id)).filter((node): node is Node => Boolean(node))
    if (!members.length) continue
    const box = boundsOf(members)
    visibleNodes.push({
      id: groupNodeId(group.task_id),
      type: GROUP_NODE_TYPE,
      position: {
        x: Math.round(box.x + box.w / 2 - GROUP_NODE_WIDTH / 2),
        y: Math.round(box.y + box.h / 2 - GROUP_NODE_HEIGHT / 2),
      },
      width: GROUP_NODE_WIDTH,
      height: GROUP_NODE_HEIGHT,
      // React Flow 接手節點時，沒有 measured 的節點會被清掉把手位置，接到它的邊就永遠畫不出來
      //（工具方塊的 measured 由畫布量完寫回節點狀態；群組方塊是每次摺疊現組的，尺寸固定就直接帶上）
      measured: { width: GROUP_NODE_WIDTH, height: GROUP_NODE_HEIGHT },
      data: {
        group,
        inputHandles: Array.from(inputHandles.get(group.task_id) ?? []),
        outputHandles: Array.from(outputHandles.get(group.task_id) ?? []),
        reports: reports ?? null,
        onExpand,
      } satisfies GroupNodeData,
    })
  }

  const sourceEdges = (graph.edges ?? []).map((edge, index) => {
    const flowEdge = edges.find((item) => item.id === edge.id) ?? edges[index]
    return { edge, flowEdge }
  })
  const merged = new Map<string, { edge: Edge; count: number; ids: string[] }>()
  const untouched: Edge[] = []
  for (const { edge, flowEdge } of sourceEdges) {
    const sourceGroup = nodeToGroup.get(edge.source)
    const targetGroup = nodeToGroup.get(edge.target)
    if (sourceGroup && targetGroup && sourceGroup.task_id === targetGroup.task_id) continue
    if (!sourceGroup && !targetGroup) {
      // 兩端都不在摺疊群組裡：畫布上的邊原樣保留。以前也走下面的重組，沒寫來源埠的邊會變成
      // sourceHandle null，React Flow 找不到把手就整條丟掉——使用者看到「摺疊後工具間的線不見了」。
      if (flowEdge) untouched.push(flowEdge)
      continue
    }
    const source = sourceGroup ? groupNodeId(sourceGroup.task_id) : edge.source
    const target = targetGroup ? groupNodeId(targetGroup.task_id) : edge.target
    // 非群組那一端沿用畫布邊的把手（toFlowEdges 已把空的來源埠補成第一個輸出埠）
    const sourceHandle = sourceGroup ? groupHandleId(edge.source, edge.source_handle) : (flowEdge?.sourceHandle ?? edge.source_handle ?? '')
    const targetHandle = targetGroup ? groupHandleId(edge.target, edge.target_handle) : (flowEdge?.targetHandle ?? edge.target_handle ?? '')
    const key = edgeKey(source, sourceHandle, target, targetHandle)
    const existing = merged.get(key)
    if (existing) {
      existing.count += 1
      if (flowEdge?.id) existing.ids.push(flowEdge.id)
      continue
    }
    const sourceNode = payloads.get(edge.source)
    const portType = edgeSourceType(edge, payloads, defs)
    const next: Edge = {
      ...(flowEdge ?? {}),
      id: `${source}.${sourceHandle}-${target}.${targetHandle}`,
      source,
      target,
      sourceHandle: sourceHandle || null,
      targetHandle: targetHandle || null,
      ...edgeProps(portType, sourceNode?.type === 'note'),
      data: { ...((flowEdge?.data as Record<string, unknown> | undefined) ?? {}), portType, originalCount: 1 },
    }
    merged.set(key, { edge: next, count: 1, ids: flowEdge?.id ? [flowEdge.id] : [] })
  }

  return {
    nodes: visibleNodes,
    edges: [...untouched, ...Array.from(merged.values()).map(({ edge, count, ids }) => ({
      ...edge,
      id: count > 1 ? `${edge.id}#${count}` : edge.id,
      label: count > 1 ? String(count) : edge.label,
      data: { ...(edge.data as Record<string, unknown> | undefined), originalCount: count, originalEdgeIds: ids },
    }))],
  }
}

export function expandOnDrop(graph: FlowGraph, taskId: string, delta: { x: number; y: number }): FlowGraph {
  if (delta.x === 0 && delta.y === 0) return graph
  const members = new Set(groupsOf(graph).find((group) => group.task_id === taskId)?.node_ids ?? [])
  if (!members.size) return graph
  return {
    ...graph,
    nodes: graph.nodes.map((node) => {
      if (!members.has(node.id)) return node
      const position = node.position ?? { x: 0, y: 0 }
      return { ...node, position: { x: Math.round(position.x + delta.x), y: Math.round(position.y + delta.y) } }
    }),
  }
}
