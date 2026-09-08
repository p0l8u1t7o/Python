import type { BoardData, BoardRun } from '@/lib/board'
import { evaluateValues, pickImage, runToBoard } from '@/lib/board'
import type { DashboardCell, DashboardData, DashboardLayout, DashboardRuleOp, DashboardWidget, Overlay, RunReport } from '@/lib/types'

export const DEFAULT_DASHBOARD_LAYOUT: DashboardLayout = {
  rows: 2,
  cols: 4,
  cells: [
    { id: 'image', row: 1, col: 1, row_span: 2, col_span: 2 },
    { id: 'verdict', row: 1, col: 3, row_span: 1, col_span: 1 },
    { id: 'stats', row: 1, col: 4, row_span: 1, col_span: 1 },
    { id: 'control', row: 2, col: 3, row_span: 1, col_span: 2 },
  ],
  bars: { top: true, bottom: false, left: false, right: false },
  default_flow_id: null,
  widgets: [
    { id: 'latest_image', type: 'image', cell: 'image', props: { overlays: true, crosshair: false, history: 1 }, source: { kind: 'image' } },
    { id: 'verdict', type: 'verdict', cell: 'verdict', props: {}, source: { kind: 'status' } },
    { id: 'today', type: 'stats', cell: 'stats', props: {}, source: { kind: 'counts' } },
    { id: 'run', type: 'run_control', cell: 'control', props: { flow_id: 1 } },
  ],
  theme: {},
}

export interface DashboardImage {
  ref: string
  width: number
  height: number
  overlays: Overlay[]
}

export function flowKey(flowId: number): string {
  return String(flowId)
}

export function isMissingFlow(pack: unknown): pack is { missing: true } {
  return typeof pack === 'object' && pack !== null && 'missing' in pack && (pack as { missing?: unknown }).missing === true
}

export function resolveFlow(widget: DashboardWidget, layout: DashboardLayout): number | null {
  const raw = widget.source?.flow_id ?? widget.props?.flow_id ?? layout.default_flow_id ?? null
  const value = typeof raw === 'string' ? Number(raw) : raw
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

export function dashboardFlowIds(layout: DashboardLayout): number[] {
  const found = new Set<number>()
  const add = (value: unknown) => {
    const id = typeof value === 'string' ? Number(value) : value
    if (typeof id === 'number' && Number.isFinite(id) && id > 0) found.add(id)
  }
  add(layout.default_flow_id)
  for (const widget of layout.widgets) {
    add(widget.source?.flow_id)
    add(widget.props?.flow_id)
    const items = widget.props?.items
    if (Array.isArray(items)) {
      for (const item of items) {
        if (typeof item === 'object' && item !== null) add((item as { flow_id?: unknown }).flow_id)
      }
    }
  }
  return [...found]
}

export function flowPack(data: DashboardData | undefined, flowId: number | null): BoardData | null {
  if (!data || flowId === null) return null
  const pack = data.flows[flowKey(flowId)]
  return pack && !isMissingFlow(pack) ? pack : null
}

export function latestBoardRun(pack: BoardData | null, liveRun?: RunReport | null): BoardRun | null {
  if (liveRun) return runToBoard(liveRun, pack?.config)
  return pack?.run ?? null
}

export function valueOf(data: DashboardData | undefined, flowId: number | null, key: string | undefined, liveRun?: RunReport | null): unknown {
  if (!key) return undefined
  if (key.startsWith('station.')) return data?.variables.station[key.slice(8)]
  if (key === 'station') return data?.device.station_id
  if (key === 'version') return data?.device.version
  if (key === 'lock') return data?.device.lock.locked
  const pack = flowPack(data, flowId)
  const liveOutputs = liveRun?.outputs ?? {}
  if (key in liveOutputs) return liveOutputs[key]
  const value = pack?.values.find((item) => item.key === key)
  if (value) return value.value
  if (pack?.run && key in (pack.run as unknown as Record<string, unknown>)) return (pack.run as unknown as Record<string, unknown>)[key]
  if (pack?.variables && key in pack.variables) return pack.variables[key]
  if (pack?.stats && key in pack.stats) return pack.stats[key]
  if (pack?.counts && key in (pack.counts as unknown as Record<string, unknown>)) return (pack.counts as unknown as Record<string, unknown>)[key]
  return undefined
}

export function imageOf(data: DashboardData | undefined, flowId: number | null, widget: DashboardWidget, liveRun?: RunReport | null): DashboardImage | null {
  const pack = flowPack(data, flowId)
  if (liveRun) {
    const img = pickImage(liveRun, stringProp(widget, 'node') ?? stringProp(widget, 'port') ?? pack?.config.image)
    if (img) return { ...img, overlays: widget.props?.overlays === false ? [] : Object.values(liveRun.nodes ?? {}).flatMap((node) => node.overlays ?? []) }
  }
  const run = pack?.run
  if (!run?.image) return null
  return {
    ...run.image,
    overlays: widget.props?.overlays === false ? [] : run.overlays ?? [],
  }
}

export function evalRule(op: DashboardRuleOp | string | undefined, value: unknown, target: unknown, target2?: unknown): boolean {
  const actual = toComparable(value)
  const left = toComparable(target)
  const right = toComparable(target2)
  switch (op) {
    case 'eq':
      return actual === left
    case 'ne':
      return actual !== left
    case 'gt':
      return typeof actual === 'number' && typeof left === 'number' && actual > left
    case 'gte':
      return typeof actual === 'number' && typeof left === 'number' && actual >= left
    case 'lt':
      return typeof actual === 'number' && typeof left === 'number' && actual < left
    case 'lte':
      return typeof actual === 'number' && typeof left === 'number' && actual <= left
    case 'between':
      return typeof actual === 'number' && typeof left === 'number' && typeof right === 'number' && actual >= left && actual <= right
    case 'contains':
      return String(value ?? '').includes(String(target ?? ''))
    default:
      return false
  }
}

export function templateText(template: string | undefined, data: DashboardData | undefined, flowId: number | null, liveRun?: RunReport | null): string {
  const text = template || '{verdict}'
  const pack = flowPack(data, flowId)
  const run = latestBoardRun(pack, liveRun)
  return text.replace(/\{([^}]+)\}/g, (_match, key: string) => {
    const name = key.trim()
    if (name === 'run_id') return run?.id ?? ''
    if (name === 'verdict') return run?.verdict ?? run?.status?.toUpperCase() ?? ''
    if (name === 'status') return run?.status ?? ''
    if (name === 'flow') return pack?.flow.name ?? ''
    if (name === 'station') return data?.device.station_id ?? ''
    const value = valueOf(data, flowId, name, liveRun)
    return value === undefined || value === null ? '' : String(value)
  })
}

export function cellById(layout: DashboardLayout, id: string | undefined): DashboardCell | null {
  if (!id) return null
  return layout.cells.find((cell) => cell.id === id) ?? null
}

export function widgetById(layout: DashboardLayout, id: string): DashboardWidget | null {
  return layout.widgets.find((widget) => widget.id === id) ?? null
}

export function nestedWidgetIds(layout: DashboardLayout): Set<string> {
  const ids = new Set<string>()
  for (const widget of layout.widgets) {
    const children = widget.props?.children
    if (Array.isArray(children)) for (const id of children) if (typeof id === 'string') ids.add(id)
    const tabs = widget.props?.tabs
    if (Array.isArray(tabs)) {
      for (const tab of tabs) {
        const tabChildren = typeof tab === 'object' && tab !== null ? (tab as { children?: unknown }).children : null
        if (Array.isArray(tabChildren)) for (const id of tabChildren) if (typeof id === 'string') ids.add(id)
      }
    }
  }
  return ids
}

export function stringProp(widget: DashboardWidget, key: string): string | undefined {
  const value = widget.props?.[key]
  return typeof value === 'string' && value ? value : undefined
}

export function numberProp(widget: DashboardWidget, key: string, fallback: number): number {
  const value = widget.props?.[key]
  const number = typeof value === 'string' ? Number(value) : value
  return typeof number === 'number' && Number.isFinite(number) ? number : fallback
}

export function booleanProp(widget: DashboardWidget, key: string, fallback: boolean): boolean {
  const value = widget.props?.[key]
  return typeof value === 'boolean' ? value : fallback
}

export function valueRows(data: DashboardData | undefined, flowId: number | null, liveRun?: RunReport | null) {
  const pack = flowPack(data, flowId)
  if (liveRun) return evaluateValues(pack?.config, liveRun.outputs ?? {})
  return pack?.values ?? []
}

function toComparable(value: unknown): string | number | boolean | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'boolean') return value
  if (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value))) return Number(value)
  if (value === null || value === undefined) return null
  return String(value)
}
