/**
 * graph JSON ⇄ React Flow 的映射與版面演算法。
 * payload（GraphNode）是編輯器自己那份真相；React Flow node.data 只是投影。
 */
import { MarkerType, type Edge, type Node } from '@xyflow/react'

import { DECORATION_TYPES } from '@/lib/graphValidation'
import { FLOW_HANDLE, compatible } from '@/lib/ports'
import { PARAM_PREFIX } from '@/lib/types'
import type { FlowGraph, GraphEdge, GraphNode, NodeReport, PortType, ToolParam, ToolPort, ToolTypeDef } from '@/lib/types'

export const DRAG_MIME = 'application/x-vs-tool'
export const HISTORY_LIMIT = 50
/** 橫向排列：欄距與列距 */
const LAYOUT_X = 300
const LAYOUT_Y = 150

export interface ToolNodeData extends Record<string, unknown> {
  definition?: ToolTypeDef
  label: string
  description: string
  enabled: boolean
  color: string
  params: Record<string, unknown>
  /** 上一次 run 的節點報告（狀態、耗時） */
  report?: NodeReport
  /** 耗時佔該次 run 最慢節點的比例（0~1）；最慢的著紅，一眼看出瓶頸 */
  heat?: number
  running?: boolean
  problem?: string
  /** 有 flow 邊連入 → 畫控制輸入菱形（其實一律畫，因為連線前不知道） */
}

export function nextNodeId(existing: Set<string>, type: string): string {
  for (let index = 1; index < 10000; index += 1) {
    const candidate = `${type}-${index}`
    if (!existing.has(candidate)) return candidate
  }
  return `${type}-${Date.now()}`
}

export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable
}

/**
 * 參數埠：把一個參數外露成輸入埠（`param:<key>`），接上上游就改吃那個值。
 * 型別對照與黑名單跟後端 `apps/vision/tools/base.py` 同一份——`code` 綁上去會繞過腳本核准，
 * `images`／`asset`／`source` 是資源指標不是值（執行前要先載入）。
 */
const PARAM_PORT_TYPE: Record<string, PortType> = { number: 'number', range: 'number', boolean: 'bool', roi: 'region', json: 'any' }
export const UNBINDABLE_KINDS = new Set(['code', 'images', 'asset', 'source'])

export function bindableParams(definition: ToolTypeDef | undefined): ToolParam[] {
  return (definition?.params ?? []).filter((p) => !UNBINDABLE_KINDS.has(p.kind))
}

export function paramPort(definition: ToolTypeDef | undefined, handle: string): ToolPort | undefined {
  if (!handle.startsWith(PARAM_PREFIX)) return undefined
  const spec = definition?.params?.find((p) => p.key === handle.slice(PARAM_PREFIX.length))
  if (!spec || UNBINDABLE_KINDS.has(spec.kind)) return undefined
  return { key: handle, label: spec.label || spec.key, type: PARAM_PORT_TYPE[spec.kind] ?? 'string', required: false, multiple: false, tone: 'neutral', implicit: true }
}

/** 節點外露的參數 → 附加在定義上的輸入埠（畫布上才畫得出把手）。 */
export function withParamPorts(definition: ToolTypeDef | undefined, exposed: string[] | undefined): ToolTypeDef | undefined {
  if (!definition || !exposed?.length) return definition
  const extra = exposed.map((key) => paramPort(definition, `${PARAM_PREFIX}${key}`)).filter((p): p is ToolPort => Boolean(p))
  return extra.length ? { ...definition, inputs: [...definition.inputs, ...extra] } : definition
}

/** 一個分支節點最多幾條路（與後端 tools/base.py 的 MAX_CASES 同步）。 */
export const MAX_CASES = 16

/** `switch` 這種「一個案例一條路」的工具：依節點設定長出 case_1…case_N 的分支埠。 */
export function withCasePorts(definition: ToolTypeDef | undefined, payload: GraphNode): ToolTypeDef | undefined {
  const key = definition?.cases_param
  if (!definition || !key) return definition
  const lines = String((payload.params ?? {})[key] ?? '').split('\n').map((s) => s.trim()).filter(Boolean).slice(0, MAX_CASES)
  if (!lines.length) return definition
  const cases: ToolPort[] = lines.map((label, i) => ({ key: `case_${i + 1}`, label: label.slice(0, 40), type: 'flow', required: false, multiple: false, tone: 'neutral' }))
  return { ...definition, outputs: [...cases, ...definition.outputs] }
}

function firstImageInput(definition: ToolTypeDef | undefined): ToolPort | undefined {
  const inputs = definition?.inputs ?? []
  return inputs.find((p) => p.type === 'image' && p.required) ?? inputs.find((p) => p.type === 'image')
}

function firstSourceImageOutput(node: GraphNode, definition: ToolTypeDef | undefined): string | null {
  if (DECORATION_TYPES.has(node.type)) return null
  const declared = definition?.outputs.find((p) => p.type === 'image' && p.implicit !== true)
  return declared?.key ?? '_image'
}

export function autoConnectOnInsert(
  graph: FlowGraph,
  newNodeId: string,
  selectedNodeId: string | null,
  defs: Map<string, ToolTypeDef>,
): GraphEdge | null {
  const nodes = graph.nodes ?? []
  const newNode = nodes.find((node) => node.id === newNodeId)
  const targetPort = newNode ? firstImageInput(defs.get(newNode.type)) : undefined
  if (!newNode || !targetPort) return null

  let sourceNode: GraphNode | undefined
  let sourceHandle: string | null = null
  if (selectedNodeId && selectedNodeId !== newNodeId) {
    const selected = nodes.find((node) => node.id === selectedNodeId)
    const handle = selected ? firstSourceImageOutput(selected, defs.get(selected.type)) : null
    if (selected && handle) {
      sourceNode = selected
      sourceHandle = handle
    }
  } else if (!selectedNodeId) {
    sourceNode = nodes.find((node) => node.type === 'image_source' || node.type === 'fixed_image')
    sourceHandle = sourceNode ? 'image' : null
  }

  if (!sourceNode || !sourceHandle || sourceNode.id === newNodeId) return null
  if (!compatible('image', targetPort.type)) return null
  return {
    id: `e-auto-${sourceNode.id}.${sourceHandle}-${newNodeId}.${targetPort.key}`,
    source: sourceNode.id,
    target: newNodeId,
    source_handle: sourceHandle,
    target_handle: targetPort.key,
  }
}

export function nodeDataFrom(payload: GraphNode, definition: ToolTypeDef | undefined): ToolNodeData {
  return {
    definition: withCasePorts(withParamPorts(definition, payload.exposed_params), payload),
    label: payload.label ?? '',
    description: payload.description ?? '',
    enabled: payload.enabled !== false,
    color: payload.color ?? '',
    params: payload.params ?? {},
  }
}

export function toFlowNode(payload: GraphNode, definition: ToolTypeDef | undefined, index = 0): Node {
  const decoration = DECORATION_TYPES.has(payload.type)
  return {
    id: payload.id,
    type: decoration ? 'note' : 'tool',
    position: payload.position ?? { x: 80 + (index % 5) * LAYOUT_X, y: 80 + Math.floor(index / 5) * LAYOUT_Y },
    ...(decoration && payload.width ? { width: payload.width } : {}),
    ...(decoration && payload.height ? { height: payload.height } : {}),
    data: nodeDataFrom(payload, definition),
  }
}

export function toFlowNodes(graph: FlowGraph, defs: Map<string, ToolTypeDef>): Node[] {
  return (graph.nodes ?? []).map((node, index) => toFlowNode(node, defs.get(node.type), index))
}

/** 邊的視覺屬性：來源埠型別上色（在 FlowEdge 元件內讀 data.portType）。 */
export function edgeProps(sourceType: string, sourceIsNote: boolean): Partial<Edge> {
  if (sourceIsNote) return { type: 'flow', data: { portType: 'note' }, style: { strokeDasharray: '6 4' } }
  return {
    type: 'flow',
    data: { portType: sourceType },
    markerEnd: sourceType === 'flow' ? { type: MarkerType.ArrowClosed, color: 'var(--port-flow)' } : undefined,
  }
}

export function toFlowEdges(graph: FlowGraph, defs: Map<string, ToolTypeDef>): Edge[] {
  const byId = new Map((graph.nodes ?? []).map((n) => [n.id, n]))
  return (graph.edges ?? []).map((edge, index) => {
    const source = byId.get(edge.source)
    const def = source ? defs.get(source.type) : undefined
    const sourceHandle = edge.source_handle || def?.outputs[0]?.key || ''
    const sourceType = def?.outputs.find((p) => p.key === sourceHandle)?.type ?? 'any'
    return {
      id: edge.id ?? `e-${edge.source}.${sourceHandle}-${edge.target}.${edge.target_handle ?? ''}-${index}`,
      source: edge.source,
      target: edge.target,
      sourceHandle: sourceHandle || null,
      targetHandle: edge.target_handle || null,
      ...edgeProps(sourceType, source?.type === 'note'),
    }
  })
}

export function graphFrom(flowNodes: Node[], flowEdges: Edge[], payloads: Map<string, GraphNode>): FlowGraph {
  const nodes: GraphNode[] = flowNodes.map((node) => {
    const payload = payloads.get(node.id)
    const decoration = DECORATION_TYPES.has(payload?.type ?? '')
    const width = node.width ?? payload?.width
    const height = node.height ?? payload?.height
    return {
      ...(payload ?? { id: node.id, type: 'note' }),
      id: node.id,
      position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
      ...(decoration && width ? { width: Math.round(width) } : {}),
      ...(decoration && height ? { height: Math.round(height) } : {}),
    }
  })
  const edges: GraphEdge[] = flowEdges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    source_handle: edge.sourceHandle ?? '',
    target_handle: edge.targetHandle ?? '',
  }))
  return { nodes, edges }
}

/**
 * 自動排列：依「距來源的最長路徑」分欄（左→右），每欄依父節點平均列排序。
 * note 不動。
 */
export function computeLayout(graph: FlowGraph): Map<string, { x: number; y: number }> {
  const executable = (graph.nodes ?? []).filter((node) => !DECORATION_TYPES.has(node.type))
  const ids = executable.map((n) => n.id)
  const idSet = new Set(ids)
  const edges = (graph.edges ?? []).filter((e) => idSet.has(e.source) && idSet.has(e.target))
  const incoming = new Map<string, string[]>()
  for (const edge of edges) {
    const list = incoming.get(edge.target)
    if (list) list.push(edge.source)
    else incoming.set(edge.target, [edge.source])
  }
  const rank = new Map<string, number>(ids.map((id) => [id, 0]))
  for (let pass = 0; pass < ids.length; pass += 1) {
    let moved = false
    for (const edge of edges) {
      const proposed = Math.min((rank.get(edge.source) ?? 0) + 1, ids.length)
      if (proposed > (rank.get(edge.target) ?? 0)) {
        rank.set(edge.target, proposed)
        moved = true
      }
    }
    if (!moved) break
  }
  const columns = new Map<number, string[]>()
  for (const id of ids) {
    const col = rank.get(id) ?? 0
    const list = columns.get(col)
    if (list) list.push(id)
    else columns.set(col, [id])
  }
  const row = new Map<string, number>()
  const positions = new Map<string, { x: number; y: number }>()
  for (const col of [...columns.keys()].sort((a, b) => a - b)) {
    const members = columns.get(col) ?? []
    const keyed = members.map((id) => {
      const parents = (incoming.get(id) ?? []).map((p) => row.get(p)).filter((v): v is number => v !== undefined)
      const barycenter = parents.length ? parents.reduce((s, v) => s + v, 0) / parents.length : Number.MAX_SAFE_INTEGER
      return { id, barycenter }
    })
    keyed.sort((a, b) => a.barycenter - b.barycenter || a.id.localeCompare(b.id))
    keyed.forEach((entry, index) => {
      row.set(entry.id, index)
      positions.set(entry.id, { x: 60 + col * LAYOUT_X, y: 60 + index * LAYOUT_Y })
    })
  }
  return positions
}

/** 目標把手是否為控制輸入 */
export function isFlowHandle(handle: string | null | undefined): boolean {
  return handle === FLOW_HANDLE
}
