/**
 * 節點介面（PRODUCT-DIRECTION v2 §5）：`node.interface = { inputs: PortSpec[], outputs: PortSpec[], params?: ParamSpec[] }`。
 * - 輸出的 `alias`＝發布成 run 具名輸出的名稱（取代 params._publish）。
 * - 輸入的 key 可以是 `param:<key>`（參數訂閱埠，取代 exposed_params）。
 * - `exposed`／`order` 是畫布上要不要畫、由上至下的順序（複合工具時＝對外介面）。
 * 與後端 tools/base.py 的 node_interface／output_aliases／exposed_param_keys 同一套語意；這裡全是純函式，回傳可直接 onChange 的 patch。
 */
import { PARAM_PREFIX, type GraphNode, type NodeInterface, type PortSpec } from './types'

function items<T extends { key: string }>(raw: unknown): T[] {
  return Array.isArray(raw) ? raw.filter((i): i is T => Boolean(i && typeof i === 'object' && typeof (i as T).key === 'string' && (i as T).key)) : []
}

export function nodeInterface(node: Pick<GraphNode, 'interface'> | undefined): Required<NodeInterface> {
  const raw = node?.interface && typeof node.interface === 'object' ? node.interface : {}
  return { inputs: items<PortSpec>(raw.inputs), outputs: items<PortSpec>(raw.outputs), params: items(raw.params) }
}

/** 輸出埠 → 具名輸出名稱（只回有 alias 的）。 */
export function outputAliases(node: Pick<GraphNode, 'interface'> | undefined): Record<string, string> {
  const out: Record<string, string> = {}
  for (const spec of nodeInterface(node).outputs) {
    const alias = (spec.alias ?? '').trim()
    if (alias) out[spec.key] = alias
  }
  return out
}

/** 外露成輸入埠的參數鍵（`param:<key>` 且 exposed 不是 false）。 */
export function exposedParamKeys(node: Pick<GraphNode, 'interface'> | undefined): string[] {
  return nodeInterface(node).inputs.filter((spec) => spec.key.startsWith(PARAM_PREFIX) && spec.exposed !== false).map((spec) => spec.key.slice(PARAM_PREFIX.length))
}

/** 沒有任何資料時把 interface 整個拿掉，圖裡不留空物件。 */
function compact(iface: Required<NodeInterface>): Partial<GraphNode> {
  const out: NodeInterface = {}
  if (iface.inputs.length) out.inputs = iface.inputs
  if (iface.outputs.length) out.outputs = iface.outputs
  if (iface.params.length) out.params = iface.params
  return { interface: Object.keys(out).length ? out : undefined }
}

/** 設定／清除一個輸出埠的具名輸出名稱。 */
export function withOutputAlias(node: Pick<GraphNode, 'interface'>, port: string, alias: string): Partial<GraphNode> {
  const iface = nodeInterface(node)
  const clean = alias.trim()
  const index = iface.outputs.findIndex((spec) => spec.key === port)
  if (clean) {
    if (index >= 0) iface.outputs[index] = { ...iface.outputs[index], alias: clean }
    else iface.outputs.push({ key: port, alias: clean })
  } else if (index >= 0) {
    const { alias: _dropped, ...rest } = iface.outputs[index]
    if (Object.keys(rest).length === 1) iface.outputs.splice(index, 1)
    else iface.outputs[index] = rest
  }
  return compact(iface)
}

/** 把參數外露成輸入埠（或收回）。 */
export function withParamExposed(node: Pick<GraphNode, 'interface'>, paramKey: string, exposed: boolean): Partial<GraphNode> {
  const iface = nodeInterface(node)
  const key = `${PARAM_PREFIX}${paramKey}`
  const index = iface.inputs.findIndex((spec) => spec.key === key)
  if (exposed) {
    if (index >= 0) iface.inputs[index] = { ...iface.inputs[index], exposed: true }
    else iface.inputs.push({ key, exposed: true })
  } else if (index >= 0) {
    iface.inputs.splice(index, 1)
  }
  return compact(iface)
}
