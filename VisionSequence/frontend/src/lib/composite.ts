/**
 * 複合工具（PRODUCT-DIRECTION v2 §3）的純函式：
 * - `encapsulateSelection`：把畫布上選取的節點封裝成一個工具（內部圖＋對外介面＋取代它們的實例節點）
 * - `interfaceCandidates`：工具編輯畫布的對外介面候選（內部節點的輸入埠／輸出埠／參數）
 * - 對外 key 的編碼 `<inner>:<port>`（與後端 apps/vision/composites.py 同一套）
 */
import { nextNodeId } from '@/components/editor/graphMapping'
import { outputAliases } from './nodeInterface'
import { FLOW_HANDLE } from './ports'
import type { FlowGraph, GraphEdge, GraphNode, NodeInterface, ParamSpec, PortSpec, ToolParam, ToolPort, ToolTypeDef } from './types'

export const COMPOSITE_PREFIX = 'composite:'
export const COMPOSITE_KEY_PATTERN = /^[a-z][a-z0-9_]{1,63}$/

export function isCompositeType(type: string | undefined): boolean {
  return typeof type === 'string' && type.startsWith(COMPOSITE_PREFIX)
}

export function compositeKeyOf(type: string): string {
  return type.slice(COMPOSITE_PREFIX.length)
}

export function compositePortKey(inner: string, port: string): string {
  return `${inner}:${port}`
}

export function splitCompositeKey(key: string): { inner: string; port: string } {
  const index = key.indexOf(':')
  return index < 0 ? { inner: key, port: '' } : { inner: key.slice(0, index), port: key.slice(index + 1) }
}

/** 名稱 → 工具 key（小寫英數與底線、字母開頭）；中文名稱給不出字母時退成 tool_N。 */
export function slugKey(label: string, fallback = 'tool'): string {
  const ascii = label.normalize('NFKD').replace(/[^\x20-\x7e]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
  const base = /^[a-z]/.test(ascii) ? ascii : ascii ? `${fallback}_${ascii}` : fallback
  return base.slice(0, 64)
}

export interface PortCandidate {
  key: string
  node: GraphNode
  port: ToolPort
  label: string
  /** 內部已經接了線的輸入埠不能對外（一個埠只能有一個來源） */
  connectedInside: boolean
}

export interface ParamCandidate {
  key: string
  node: GraphNode
  param: ToolParam
  label: string
}

function nodeLabel(node: GraphNode, def: ToolTypeDef | undefined): string {
  return node.label || def?.label || node.id
}

/** 工具內部所有節點的埠與參數，依節點順序列出（介面編輯區的清單來源）。 */
export function interfaceCandidates(graph: FlowGraph, defs: Map<string, ToolTypeDef>): { inputs: PortCandidate[]; outputs: PortCandidate[]; params: ParamCandidate[] } {
  const connected = new Set(graph.edges.map((edge) => `${edge.target}:${edge.target_handle ?? ''}`))
  const inputs: PortCandidate[] = []
  const outputs: PortCandidate[] = []
  const params: ParamCandidate[] = []
  for (const node of graph.nodes) {
    if (node.type === 'note') continue
    const def = defs.get(node.type)
    if (!def) continue
    const owner = nodeLabel(node, def)
    for (const port of def.inputs) {
      if (port.key.startsWith('_') || port.key.startsWith('param:')) continue
      inputs.push({ key: compositePortKey(node.id, port.key), node, port, label: `${owner}: ${port.label}`, connectedInside: connected.has(`${node.id}:${port.key}`) })
    }
    for (const port of def.outputs) {
      if (port.implicit) continue
      outputs.push({ key: compositePortKey(node.id, port.key), node, port, label: `${owner}: ${port.label}`, connectedInside: false })
    }
    for (const param of def.params) {
      if (param.kind === 'code') continue
      params.push({ key: compositePortKey(node.id, param.key), node, param, label: `${owner}: ${param.label}` })
    }
  }
  return { inputs, outputs, params }
}

export interface Encapsulation {
  /** 工具的內部圖（節點位置平移到左上角、具名輸出名稱拿掉） */
  toolGraph: FlowGraph
  /** 對外介面：跨越選取邊界的埠、未接線的必填輸入、原本已發布的輸出 */
  interface: NodeInterface
  /** 取代那些節點的實例（原本的具名輸出名稱搬到它身上） */
  instance: GraphNode
  /** 封裝後的流程圖 */
  graph: FlowGraph
}

/** 把選取的節點封裝成工具；沒有可封裝的節點（全是註解）回 null。 */
export function encapsulateSelection(graph: FlowGraph, selectedIds: string[], defs: Map<string, ToolTypeDef>, key: string, label: string): Encapsulation | null {
  const chosen = new Set(selectedIds)
  const inner = graph.nodes.filter((node) => chosen.has(node.id) && node.type !== 'note')
  if (!inner.length) return null
  const innerIds = new Set(inner.map((node) => node.id))
  const edges = graph.edges
  const internal = edges.filter((edge) => innerIds.has(edge.source) && innerIds.has(edge.target))
  const incoming = edges.filter((edge) => innerIds.has(edge.target) && !innerIds.has(edge.source))
  const outgoing = edges.filter((edge) => innerIds.has(edge.source) && !innerIds.has(edge.target))
  const internallyFed = new Set(internal.map((edge) => `${edge.target}:${edge.target_handle ?? ''}`))

  const inputSpecs: PortSpec[] = []
  const seenIn = new Set<string>()
  const addInput = (nodeId: string, port: string) => {
    const spec = compositePortKey(nodeId, port)
    if (seenIn.has(spec)) return
    seenIn.add(spec)
    inputSpecs.push({ key: spec, exposed: true, order: inputSpecs.length })
  }
  for (const edge of incoming) {
    const handle = edge.target_handle ?? ''
    if (handle === FLOW_HANDLE || handle.startsWith('_')) continue
    addInput(edge.target, handle)
  }
  for (const node of inner) {
    const def = defs.get(node.type)
    for (const port of def?.inputs ?? []) {
      if (!port.required || port.key.startsWith('_') || internallyFed.has(`${node.id}:${port.key}`)) continue
      if (port.type === 'region' && node.params?.[port.key] && typeof node.params[port.key] === 'object') continue
      addInput(node.id, port.key)
    }
  }

  const outputSpecs: PortSpec[] = []
  const instanceAliases: PortSpec[] = []
  const seenOut = new Set<string>()
  const addOutput = (nodeId: string, port: string) => {
    const spec = compositePortKey(nodeId, port)
    if (seenOut.has(spec)) return
    seenOut.add(spec)
    outputSpecs.push({ key: spec, exposed: true, order: outputSpecs.length })
  }
  for (const edge of outgoing) {
    const def = defs.get(graph.nodes.find((node) => node.id === edge.source)?.type ?? '')
    const handle = edge.source_handle || def?.outputs[0]?.key || ''
    if (!handle) continue
    addOutput(edge.source, handle)
  }
  for (const node of inner) {
    for (const [port, alias] of Object.entries(outputAliases(node))) {
      addOutput(node.id, port)
      instanceAliases.push({ key: compositePortKey(node.id, port), alias })
    }
  }

  const minX = Math.min(...inner.map((node) => node.position?.x ?? 0))
  const minY = Math.min(...inner.map((node) => node.position?.y ?? 0))
  const toolGraph: FlowGraph = {
    nodes: inner.map((node) => {
      const copy: GraphNode = JSON.parse(JSON.stringify(node))
      copy.position = { x: (node.position?.x ?? 0) - minX + 40, y: (node.position?.y ?? 0) - minY + 40 }
      stripAliases(copy)
      return copy
    }),
    edges: internal.map((edge) => ({ ...edge })),
  }

  const existing = new Set(graph.nodes.map((node) => node.id))
  const instance: GraphNode = {
    id: nextNodeId(existing, key),
    type: `${COMPOSITE_PREFIX}${key}`,
    label,
    params: {},
    position: {
      x: Math.round(inner.reduce((sum, node) => sum + (node.position?.x ?? 0), 0) / inner.length),
      y: Math.round(inner.reduce((sum, node) => sum + (node.position?.y ?? 0), 0) / inner.length),
    },
    ...(instanceAliases.length ? { interface: { outputs: instanceAliases } } : {}),
  }

  const rest = graph.nodes.filter((node) => !innerIds.has(node.id))
  const seenEdges = new Set<string>()
  const rewired: GraphEdge[] = []
  const push = (edge: GraphEdge) => {
    const signature = `${edge.source}|${edge.source_handle ?? ''}|${edge.target}|${edge.target_handle ?? ''}`
    if (seenEdges.has(signature)) return
    seenEdges.add(signature)
    rewired.push(edge)
  }
  for (const edge of edges) {
    if (innerIds.has(edge.source) && innerIds.has(edge.target)) continue
    if (!innerIds.has(edge.source) && !innerIds.has(edge.target)) {
      push({ ...edge })
      continue
    }
    if (innerIds.has(edge.target)) {
      const handle = edge.target_handle ?? ''
      const target_handle = handle === FLOW_HANDLE || handle.startsWith('_') ? handle : compositePortKey(edge.target, handle)
      push({ id: `${edge.source}-${instance.id}-${target_handle}`, source: edge.source, source_handle: edge.source_handle, target: instance.id, target_handle })
      continue
    }
    const def = defs.get(graph.nodes.find((node) => node.id === edge.source)?.type ?? '')
    const handle = edge.source_handle || def?.outputs[0]?.key || ''
    push({ id: `${instance.id}-${handle}-${edge.target}-${edge.target_handle ?? ''}`, source: instance.id, source_handle: compositePortKey(edge.source, handle), target: edge.target, target_handle: edge.target_handle })
  }

  return {
    toolGraph,
    interface: { inputs: inputSpecs, outputs: outputSpecs },
    instance,
    graph: { nodes: [...rest, instance], edges: rewired },
  }
}

function stripAliases(node: GraphNode): void {
  const outputs = (node.interface?.outputs ?? []).map(({ alias: _alias, ...rest }) => rest).filter((spec) => Object.keys(spec).length > 1)
  if (!node.interface) return
  const next: NodeInterface = { ...node.interface }
  if (outputs.length) next.outputs = outputs
  else delete next.outputs
  if (Object.keys(next).length) node.interface = next
  else delete node.interface
}

/** 對外參數：加入／移除／改顯示名與教導旗標。 */
export function withParamSpec(iface: NodeInterface, key: string, patch: Partial<ParamSpec> | null): NodeInterface {
  const params = [...(iface.params ?? [])]
  const index = params.findIndex((spec) => spec.key === key)
  if (patch === null) {
    if (index >= 0) params.splice(index, 1)
  } else if (index >= 0) {
    params[index] = { ...params[index], ...patch }
  } else {
    params.push({ key, order: params.length, ...patch })
  }
  const next: NodeInterface = { ...iface }
  if (params.length) next.params = params
  else delete next.params
  return next
}

/** 對外參數重排：依 key 順序寫 order。 */
export function withParamOrder(iface: NodeInterface, keys: string[]): NodeInterface {
  const byKey = new Map((iface.params ?? []).map((spec) => [spec.key, spec]))
  const params = keys.map((key, order) => ({ ...(byKey.get(key) ?? { key }), order }))
  return { ...iface, params }
}

/** 對外參數依 order 排好。 */
export function orderedParamSpecs(iface: NodeInterface): ParamSpec[] {
  return [...(iface.params ?? [])].sort((a, b) => (a.order ?? 1e9) - (b.order ?? 1e9))
}
