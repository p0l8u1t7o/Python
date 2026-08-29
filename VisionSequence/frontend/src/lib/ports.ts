/** 埠型別 → 顏色與相容規則（與 apps/vision/graph.py `_compatible` 同步；顏色照 docs/glossary.html）。 */
import type { PortType } from './types'

export const FLOW_HANDLE = '_flow'

export const PORT_COLOR: Record<PortType, string> = {
  image: 'var(--port-image)',
  number: 'var(--port-number)',
  bool: 'var(--port-bool)',
  region: 'var(--port-region)',
  flow: 'var(--port-flow)',
  list: 'var(--port-list)',
  points: 'var(--port-points)',
  contours: 'var(--port-contours)',
  matches: 'var(--port-matches)',
  string: 'var(--port-string)',
  any: 'var(--port-any)',
}

/** 說明頁圖例用：型別 → 實際色碼（與 index.css 變數同值）。 */
export const PORT_HEX: Record<PortType, string> = {
  image: '#3b82f6',
  region: '#a855f7',
  number: '#22c55e',
  bool: '#f97316',
  string: '#eab308',
  points: '#06b6d4',
  contours: '#6366f1',
  matches: '#ec4899',
  list: '#14b8a6',
  any: '#cbd5e1',
  flow: '#94a3b8',
}

export function portColor(type: string | undefined): string {
  return PORT_COLOR[(type ?? 'any') as PortType] ?? PORT_COLOR.any
}

const EXTRA: ReadonlySet<string> = new Set([
  'number>string',
  'bool>number',
  'bool>string',
  'string>any',
  'points>list',
  'matches>list',
  'contours>list',
])

export function compatible(sourceType: string, targetType: string): boolean {
  if (sourceType === 'flow' || targetType === 'flow') return sourceType === targetType
  if (sourceType === 'any' || targetType === 'any') return true
  if (sourceType === targetType) return true
  return EXTRA.has(`${sourceType}>${targetType}`)
}
