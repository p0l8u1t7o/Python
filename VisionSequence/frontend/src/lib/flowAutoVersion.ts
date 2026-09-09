import type { FlowGraph } from './types'

function stableValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableValue)
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([key, item]) => [key, stableValue(item)]),
  )
}

export function flowGraphSignature(graph: FlowGraph): string {
  return JSON.stringify(stableValue(graph))
}

export function shouldSaveDraftVersion(args: { enabled: boolean; dirty: boolean; currentSignature: string; lastSavedSignature: string | null }): boolean {
  return args.enabled && args.dirty && args.lastSavedSignature !== args.currentSignature
}
