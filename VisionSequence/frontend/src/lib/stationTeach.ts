import type { Flow, FlowGraph, StationTeachGroup, StationTeachParamItem, StationTeachRef } from './types'

export interface StationTeachFilters {
  flowId: number | ''
  toolType: string
  q: string
}

export interface StationTeachPatch {
  flow: Flow
  graph: FlowGraph
  count: number
}

export interface StationTeachSaveResult {
  flow_id: number
  flow_name: string
  ok: boolean
  count: number
  error?: unknown
}

export function stationTeachKey(ref: StationTeachRef): string {
  return `${ref.flow_id}:${ref.node_id}:${ref.param}`
}

export function stationTeachRef(row: StationTeachParamItem): StationTeachRef {
  return { flow_id: row.flow_id, node_id: row.node_id, param: row.param.key }
}

function textOf(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

export function sameStationTeachValue(a: unknown, b: unknown): boolean {
  if (Object.is(a, b)) return true
  return textOf(a) === textOf(b)
}

export function filterStationTeachItems(items: StationTeachParamItem[], filters: StationTeachFilters): StationTeachParamItem[] {
  const q = filters.q.trim().toLowerCase()
  return items.filter((item) => {
    if (filters.flowId !== '' && item.flow_id !== filters.flowId) return false
    if (filters.toolType && item.tool_type !== filters.toolType) return false
    if (!q) return true
    const haystack = [
      item.flow_name,
      item.node_label,
      item.node_id,
      item.tool_label,
      item.tool_type,
      item.param.label,
      item.param.key,
      textOf(item.value),
    ].join(' ').toLowerCase()
    return haystack.includes(q)
  })
}

/** 篩選列的選項：流程清單看全部列；工具清單只看「目前選的流程」裡有的工具，流程換了工具清單跟著變。 */
export function stationTeachOptions(items: StationTeachParamItem[], flowId: number | ''): { flows: [number, string][]; tools: [string, string][] } {
  const scoped = flowId === '' ? items : items.filter((item) => item.flow_id === flowId)
  return {
    flows: [...new Map(items.map((row) => [row.flow_id, row.flow_name] as [number, string])).entries()],
    tools: [...new Map(scoped.map((row) => [row.tool_type, row.tool_label] as [string, string])).entries()],
  }
}

export function invalidGroupItems(group: StationTeachGroup): StationTeachRef[] {
  return group.items.filter((item) => !item.valid).map((item) => ({ flow_id: item.flow_id, node_id: item.node_id, param: item.param }))
}

export function buildStationTeachPatches(flows: Flow[], rows: StationTeachParamItem[], changes: Record<string, unknown>): StationTeachPatch[] {
  const flowMap = new Map(flows.map((flow) => [flow.id, flow]))
  const rowsByKey = new Map(rows.map((row) => [stationTeachKey(stationTeachRef(row)), row]))
  const grouped = new Map<number, { row: StationTeachParamItem; value: unknown }[]>()
  for (const [key, value] of Object.entries(changes)) {
    const row = rowsByKey.get(key)
    if (!row || sameStationTeachValue(row.value, value)) continue
    const list = grouped.get(row.flow_id) ?? []
    list.push({ row, value })
    grouped.set(row.flow_id, list)
  }
  const patches: StationTeachPatch[] = []
  for (const [flowId, entries] of grouped) {
    const flow = flowMap.get(flowId)
    if (!flow) continue
    const graph = {
      ...flow.graph,
      nodes: flow.graph.nodes.map((node) => {
        const nodeEntries = entries.filter((entry) => entry.row.node_id === node.id)
        if (!nodeEntries.length) return node
        const params = { ...(node.params ?? {}) }
        for (const entry of nodeEntries) params[entry.row.param.key] = entry.value
        return { ...node, params }
      }),
    }
    patches.push({ flow, graph, count: entries.length })
  }
  return patches
}

export async function saveStationTeachPatches(
  patches: StationTeachPatch[],
  saveFlow: (patch: StationTeachPatch) => Promise<unknown>,
): Promise<StationTeachSaveResult[]> {
  return Promise.all(patches.map(async (patch) => {
    try {
      await saveFlow(patch)
      return { flow_id: patch.flow.id, flow_name: patch.flow.name, ok: true, count: patch.count }
    } catch (error) {
      return { flow_id: patch.flow.id, flow_name: patch.flow.name, ok: false, count: patch.count, error }
    }
  }))
}
