/**
 * 埠的顯示規則與順序（PRODUCT-DIRECTION v2 §2）：畫布上的節點卡片、工具頁的埠編輯區、看板／結果回送的名稱清單都讀這一份。
 *
 * 預設規則（§2-3）：
 * - 已接線 → 顯示，且不能隱藏（先移除連線）
 * - 使用者在 interface 標 `exposed: false` → 隱藏；`exposed: true` → 顯示
 * - 工具目錄標 `primary`（第一個影像埠、所有分支埠）→ 顯示
 * - 已取具名輸出名稱（alias）→ 顯示
 * - 必填輸入且未接線 → 顯示；被使用者藏起來就是「隱藏的問題埠」（節點掛徽章、nodeProblems 照樣報）
 * - 其餘 → 收合（節點上的「＋N」可就地展開）
 * 順序：interface 的 `order` 優先，沒有的依工具目錄順序，隱含埠殿後。
 */
import { inputSatisfied } from './graphValidation'
import { nodeInterface, outputAliases } from './nodeInterface'
import type { GraphEdge, GraphNode, PortSpec, ToolPort, ToolTypeDef } from './types'

export type PortSide = 'in' | 'out'

export type PortReason = 'connected' | 'hidden' | 'exposed' | 'primary' | 'alias' | 'required' | 'collapsed'

export interface PortView {
  port: ToolPort
  /** 目前畫布上畫不畫 */
  visible: boolean
  connected: boolean
  /** 為什麼顯示／不顯示（工具頁的標籤、tooltip 用） */
  reason: PortReason
  /** 必填輸入未接線（不論顯示與否） */
  missing: boolean
  /** interface 裡有人動過（exposed／order）；「還原預設」看它 */
  customised: boolean
}

export interface PortLayout {
  /** 依有效順序排好的全部埠 */
  all: PortView[]
  visible: ToolPort[]
  hidden: ToolPort[]
  /** 被藏起來、又是必填未接的輸入埠 */
  hiddenProblems: ToolPort[]
}

const ORDER_BASE = 1_000_000
const IMPLICIT_PUSH = 100_000

/** 這個節點某一側已接線的埠 key。 */
export function connectedHandles(nodeId: string, edges: GraphEdge[], side: PortSide): Set<string> {
  const out = new Set<string>()
  for (const edge of edges) {
    if (side === 'in' && edge.target === nodeId) out.add(edge.target_handle ?? '')
    if (side === 'out' && edge.source === nodeId) out.add(edge.source_handle ?? '')
  }
  return out
}

/** 工具目錄沒標 primary 時的啟發式（與後端 tools/base.py 的 _with_default_primary 同一套；動態分支埠不經過後端所以這裡也判 flow）。 */
export function isPrimaryPort(port: ToolPort, side: PortSide): boolean {
  return port.primary === true || (side === 'out' && port.type === 'flow')
}

function specsOf(node: Pick<GraphNode, 'interface'> | undefined, side: PortSide): Map<string, PortSpec> {
  const iface = nodeInterface(node)
  return new Map((side === 'in' ? iface.inputs : iface.outputs).map((spec) => [spec.key, spec]))
}

function sortKey(spec: PortSpec | undefined, port: ToolPort, index: number): number {
  if (typeof spec?.order === 'number' && Number.isFinite(spec.order)) return spec.order
  return ORDER_BASE + index + (port.implicit === true ? IMPLICIT_PUSH : 0)
}

/** 依 interface 的 order 排好的埠（沒有 order 的依目錄順序、隱含埠殿後）。 */
export function orderedPorts(ports: ToolPort[], node: Pick<GraphNode, 'interface'> | undefined, side: PortSide): ToolPort[] {
  const specs = specsOf(node, side)
  return ports
    .map((port, index) => ({ port, key: sortKey(specs.get(port.key), port, index), index }))
    .sort((a, b) => a.key - b.key || a.index - b.index)
    .map((item) => item.port)
}

export function portLayout(definition: ToolTypeDef | undefined, node: Pick<GraphNode, 'interface' | 'params'> | undefined, side: PortSide, connected: ReadonlySet<string>): PortLayout {
  const ports = side === 'in' ? (definition?.inputs ?? []) : (definition?.outputs ?? [])
  const specs = specsOf(node, side)
  const aliases = side === 'out' ? outputAliases(node) : {}
  const params = node?.params ?? {}
  const all = orderedPorts(ports, node, side).map((port): PortView => {
    const spec = specs.get(port.key)
    const isConnected = connected.has(port.key)
    const missing = side === 'in' && port.required && !inputSatisfied(port, params, connected)
    const customised = Boolean(spec && (typeof spec.exposed === 'boolean' || typeof spec.order === 'number'))
    let reason: PortReason
    if (isConnected) reason = 'connected'
    else if (spec?.exposed === false) reason = 'hidden'
    else if (spec?.exposed === true) reason = 'exposed'
    else if (isPrimaryPort(port, side)) reason = 'primary'
    else if (side === 'out' && aliases[port.key]) reason = 'alias'
    else if (missing) reason = 'required'
    else reason = 'collapsed'
    const visible = reason !== 'hidden' && reason !== 'collapsed'
    return { port, visible, connected: isConnected, reason, missing, customised }
  })
  return {
    all,
    visible: all.filter((view) => view.visible).map((view) => view.port),
    hidden: all.filter((view) => !view.visible).map((view) => view.port),
    hiddenProblems: all.filter((view) => !view.visible && view.missing).map((view) => view.port),
  }
}

/**
 * 「依下游／上游位置自動排序」：已接線的埠依對端節點的平均 y 排（連線就不會交叉），沒接線的維持原本相對順序放在後面。
 * 回傳新的 key 順序。
 */
export function autoOrderKeys(definition: ToolTypeDef | undefined, node: GraphNode, side: PortSide, edges: GraphEdge[], nodes: GraphNode[]): string[] {
  const positions = new Map(nodes.map((n) => [n.id, n.position?.y ?? 0]))
  const ordered = orderedPorts(side === 'in' ? (definition?.inputs ?? []) : (definition?.outputs ?? []), node, side)
  const linked: { key: string; y: number; index: number }[] = []
  const rest: string[] = []
  ordered.forEach((port, index) => {
    const peers = edges
      .filter((edge) => (side === 'in' ? edge.target === node.id && (edge.target_handle ?? '') === port.key : edge.source === node.id && (edge.source_handle ?? '') === port.key))
      .map((edge) => positions.get(side === 'in' ? edge.source : edge.target) ?? 0)
    if (peers.length) linked.push({ key: port.key, y: peers.reduce((sum, y) => sum + y, 0) / peers.length, index })
    else rest.push(port.key)
  })
  linked.sort((a, b) => a.y - b.y || a.index - b.index)
  return [...linked.map((item) => item.key), ...rest]
}

/**
 * 整張圖的具名輸出名稱（結果回送 `{name}`、看板／儀表板的資料來源清單）：output／format_text 步驟的 name，加上每個節點依埠順序列出的 alias。
 */
export function graphOutputNames(nodes: GraphNode[], defs: Map<string, ToolTypeDef>): string[] {
  const names = new Set<string>()
  for (const node of nodes) {
    if (node.type === 'output' || node.type === 'format_text') {
      const name = String(node.params?.name ?? '').trim()
      if (name) names.add(name)
    }
    const aliases = outputAliases(node)
    if (!Object.keys(aliases).length) continue
    const def = defs.get(node.type)
    const ordered = def ? orderedPorts(def.outputs, node, 'out').map((port) => port.key) : Object.keys(aliases)
    for (const key of ordered) if (aliases[key]) names.add(aliases[key])
    for (const key of Object.keys(aliases)) if (!ordered.includes(key)) names.add(aliases[key])
  }
  return [...names]
}
