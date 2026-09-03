/** 現場調機參數（teach=true）依拓樸順序分組：參數卡頁與批次測試調參面板共用。 */
import { paramVisible } from '@/lib/graphValidation'
import type { FlowGraph, GraphNode, ToolParam, ToolTypeDef } from '@/lib/types'
import { topoOrder } from '@/pages/FlowEditorPage'

export interface TeachGroup {
  node: GraphNode
  def: ToolTypeDef
  params: ToolParam[]
}

export function teachGroupsOf(graph: FlowGraph | null | undefined, defs: Map<string, ToolTypeDef>): TeachGroup[] {
  if (!graph) return []
  const payloads = new Map(graph.nodes.map((n) => [n.id, n]))
  const out: TeachGroup[] = []
  for (const id of topoOrder(graph.nodes, graph.edges)) {
    const node = payloads.get(id)
    const def = node ? defs.get(node.type) : undefined
    if (!node || !def) continue
    const params = def.params.filter((p) => p.teach && paramVisible(p, node.params ?? {}))
    if (params.length) out.push({ node, def, params })
  }
  return out
}
