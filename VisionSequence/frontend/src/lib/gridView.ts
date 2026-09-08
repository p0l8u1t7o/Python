import type { RunReport } from '@/lib/types'

export const GRID_COUNTS = [1, 2, 4, 6, 9] as const
export type GridCount = typeof GRID_COUNTS[number]

export interface GridBinding {
  nodeId: string
  port: string
}

export interface GridLayout {
  count: GridCount
  bindings: (GridBinding | null)[]
}

export interface GridPlacement {
  rows: number
  cols: number
}

export interface GridImage {
  ref: string
  width: number
  height: number
}

const PLACEMENTS: Record<GridCount, GridPlacement> = {
  1: { rows: 1, cols: 1 },
  2: { rows: 1, cols: 2 },
  4: { rows: 2, cols: 2 },
  6: { rows: 2, cols: 3 },
  9: { rows: 3, cols: 3 },
}

function isGridCount(value: unknown): value is GridCount {
  return GRID_COUNTS.includes(value as GridCount)
}

function cleanBinding(value: unknown): GridBinding | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null
  const raw = value as Record<string, unknown>
  return typeof raw.nodeId === 'string' && raw.nodeId && typeof raw.port === 'string' && raw.port
    ? { nodeId: raw.nodeId, port: raw.port }
    : null
}

export function gridPlacement(count: GridCount): GridPlacement {
  return PLACEMENTS[count]
}

export function normalizeGridLayout(input?: { count?: unknown; bindings?: readonly unknown[] | null } | null): GridLayout {
  const count = isGridCount(input?.count) ? input.count : 4
  const bindings = Array.from({ length: count }, (_, index) => cleanBinding(input?.bindings?.[index] ?? null))
  return { count, bindings }
}

export function setGridCount(layout: GridLayout, count: GridCount): GridLayout {
  const current = normalizeGridLayout(layout)
  return {
    count,
    bindings: Array.from({ length: count }, (_, index) => current.bindings[index] ?? null),
  }
}

export function bindGridCell(layout: GridLayout, index: number, binding: GridBinding | null): GridLayout {
  const current = normalizeGridLayout(layout)
  if (index < 0 || index >= current.count) return current
  const bindings = [...current.bindings]
  bindings[index] = binding ? { nodeId: binding.nodeId, port: binding.port } : null
  return { ...current, bindings }
}

export function removeMissingGridBindings(layout: GridLayout, nodeIds: Iterable<string>): GridLayout {
  const valid = new Set(nodeIds)
  const current = normalizeGridLayout(layout)
  return {
    ...current,
    bindings: current.bindings.map((binding) => binding && valid.has(binding.nodeId) ? binding : null),
  }
}

function asGridImage(value: unknown): GridImage | null {
  if (!value || typeof value !== 'object') return null
  const raw = value as { ref?: unknown; width?: unknown; height?: unknown }
  return typeof raw.ref === 'string' && raw.ref && typeof raw.width === 'number' && typeof raw.height === 'number'
    ? { ref: raw.ref, width: raw.width, height: raw.height }
    : null
}

export function gridCellImage(run: RunReport | null, binding: GridBinding | null, nodeIds: Iterable<string>): GridImage | null {
  if (!run || !binding) return null
  if (!new Set(nodeIds).has(binding.nodeId)) return null
  return asGridImage(run.nodes[binding.nodeId]?.outputs?.[binding.port] ?? null)
}
