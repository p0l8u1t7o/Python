/**
 * 前端的圖檢查。伺服器存檔時仍會驗證，這裡只是在操作者還盯著欄位時先說出來。
 * 回傳 i18n key + values，讓訊息跟介面語言走。
 */
import { FLOW_HANDLE, compatible } from './ports'
import type { GraphEdge, GraphNode, ToolParam, ToolTypeDef } from './types'

export type ProblemCode =
  | 'required'
  | 'notANumber'
  | 'belowMinimum'
  | 'aboveMaximum'
  | 'badJson'
  | 'inputMissing'
  | 'flowUnconnected'

export interface Problem {
  /** 參數 key；輸入埠問題用 `in:<port>`、分支用 `out:<port>` */
  key: string
  code: ProblemCode
  /** flowUnconnected 只是提示，不擋存檔 */
  severity: 'error' | 'warning'
  values: Record<string, unknown>
}

export const DECORATION_TYPES: ReadonlySet<string> = new Set(['note'])

function isBlank(value: unknown): boolean {
  return value === null || value === undefined || String(value).trim() === ''
}

/** visible_when 條件：隱藏的參數不檢查。 */
export function paramVisible(param: ToolParam, params: Record<string, unknown>): boolean {
  const cond = param.visible_when
  if (!cond) return true
  const other = params[cond.param]
  return cond.in.some((v) => v === other || String(v) === String(other ?? ''))
}

function checkParam(param: ToolParam, value: unknown): Problem | null {
  const values = { label: param.label, min: param.minimum, max: param.maximum }
  const blank = isBlank(value) || (param.kind === 'roi' && (typeof value !== 'object' || value === null))
  if (blank) {
    return param.required ? { key: param.key, code: 'required', severity: 'error', values } : null
  }
  if (param.kind === 'number') {
    const numeric = Number(value)
    if (!Number.isFinite(numeric)) return { key: param.key, code: 'notANumber', severity: 'error', values }
    if (param.minimum !== null && numeric < param.minimum)
      return { key: param.key, code: 'belowMinimum', severity: 'error', values }
    if (param.maximum !== null && numeric > param.maximum)
      return { key: param.key, code: 'aboveMaximum', severity: 'error', values }
  }
  if (param.kind === 'json' && typeof value === 'string') {
    try {
      JSON.parse(value)
    } catch {
      return { key: param.key, code: 'badJson', severity: 'error', values }
    }
  }
  return null
}

export function nodeProblems(node: GraphNode, def: ToolTypeDef | undefined, edges: GraphEdge[]): Problem[] {
  if (!def || DECORATION_TYPES.has(node.type)) return []
  const params = node.params ?? {}
  const problems: Problem[] = []
  for (const param of def.params) {
    if (!paramVisible(param, params)) continue
    const problem = checkParam(param, params[param.key] ?? param.default)
    if (problem) problems.push(problem)
  }
  const incoming = new Set(edges.filter((e) => e.target === node.id).map((e) => e.target_handle ?? ''))
  for (const port of def.inputs) {
    if (!port.required || incoming.has(port.key)) continue
    // ROI 輸入埠若同名參數已填就不算缺（工具 ctx.roi() 會退回參數）。
    if (port.type === 'region' && params[port.key] && typeof params[port.key] === 'object') continue
    problems.push({ key: `in:${port.key}`, code: 'inputMissing', severity: 'error', values: { label: port.label } })
  }
  const outgoing = new Set(edges.filter((e) => e.source === node.id).map((e) => e.source_handle ?? ''))
  for (const port of def.outputs) {
    if (port.type !== 'flow' || outgoing.has(port.key)) continue
    problems.push({ key: `out:${port.key}`, code: 'flowUnconnected', severity: 'warning', values: { label: port.label } })
  }
  return problems
}

/** node id → problems（只含 error 等級，畫在畫布上）。 */
export function graphProblems(
  nodes: GraphNode[],
  edges: GraphEdge[],
  defs: Map<string, ToolTypeDef>,
): Map<string, Problem[]> {
  const result = new Map<string, Problem[]>()
  for (const node of nodes) {
    if (node.enabled === false) continue
    const problems = nodeProblems(node, defs.get(node.type), edges).filter((p) => p.severity === 'error')
    if (problems.length) result.set(node.id, problems)
  }
  return result
}

export type ConnectRejection =
  | { code: 'incompatible'; values: Record<string, unknown> }
  | { code: 'flowOnly' | 'singleInput' | 'noteTarget' | 'cycle'; values: Record<string, unknown> }

/**
 * onConnect 用：檢查一條新邊是否合法。回 null 表示可以連。
 */
export function checkConnection(
  conn: { source: string; sourceHandle: string | null; target: string; targetHandle: string | null },
  nodes: Map<string, GraphNode>,
  edges: GraphEdge[],
  defs: Map<string, ToolTypeDef>,
): ConnectRejection | null {
  const sourceNode = nodes.get(conn.source)
  const targetNode = nodes.get(conn.target)
  if (!sourceNode || !targetNode) return { code: 'incompatible', values: {} }
  if (DECORATION_TYPES.has(targetNode.type)) return { code: 'noteTarget', values: {} }
  const sDef = defs.get(sourceNode.type)
  const tDef = defs.get(targetNode.type)
  const sHandle = conn.sourceHandle || sDef?.outputs[0]?.key || ''
  const tHandle = conn.targetHandle || tDef?.inputs[0]?.key || ''
  const sPort = sDef?.outputs.find((p) => p.key === sHandle)
  const sType = sPort?.type ?? 'any'
  const tType = tHandle === FLOW_HANDLE ? 'flow' : (tDef?.inputs.find((p) => p.key === tHandle)?.type ?? 'any')
  if (sType === 'flow' && tHandle !== FLOW_HANDLE) return { code: 'flowOnly', values: {} }
  if (!compatible(sType, tType)) {
    return {
      code: 'incompatible',
      values: { source: `${sourceNode.label || sourceNode.type}.${sHandle}`, sourceType: sType, target: `${targetNode.label || targetNode.type}.${tHandle}`, targetType: tType },
    }
  }
  if (tHandle !== FLOW_HANDLE) {
    const tPort = tDef?.inputs.find((p) => p.key === tHandle)
    if (tPort && !tPort.multiple && edges.some((e) => e.target === conn.target && (e.target_handle ?? '') === tHandle)) {
      return { code: 'singleInput', values: {} }
    }
  }
  if (reaches(conn.target, conn.source, edges)) return { code: 'cycle', values: {} }
  return null
}

/** target 是否能沿著既有的邊走到 source（若能，新邊會形成迴圈）。 */
function reaches(from: string, to: string, edges: GraphEdge[]): boolean {
  if (from === to) return true
  const seen = new Set<string>()
  const stack = [from]
  while (stack.length) {
    const id = stack.pop() as string
    if (seen.has(id)) continue
    seen.add(id)
    for (const e of edges) {
      if (e.source !== id) continue
      if (e.target === to) return true
      stack.push(e.target)
    }
  }
  return false
}
