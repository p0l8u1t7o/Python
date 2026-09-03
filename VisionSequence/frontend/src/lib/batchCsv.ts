/** 批次執行結果 → CSV（UTF-8 BOM，Excel 可直接開）。 */
import type { BatchRunItem } from '@/lib/batch'

export function csvCell(value: unknown): string {
  const text = typeof value === 'string' ? value : value === null || value === undefined ? '' : typeof value === 'object' ? JSON.stringify(value) : String(value)
  return /[",\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export function batchToCsv(items: BatchRunItem[]): string {
  const keys = [...new Set(items.flatMap((it) => Object.keys(it.outputs ?? {})))]
  const head = ['index', 'name', 'status', 'expected', 'match', 'duration_ms', ...keys, 'error', 'error_node']
  const rows = items.map((it) => [it.index + 1, it.name, it.status, it.expected, it.match === null ? '' : it.match ? 'yes' : 'no', it.duration_ms, ...keys.map((k) => csvCell(it.outputs?.[k])), it.error, it.error_node ?? ''].map(csvCell).join(','))
  return [head.join(','), ...rows].join('\r\n')
}

export function downloadCsv(text: string, filename: string): void {
  const blob = new Blob(['﻿', text], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}
