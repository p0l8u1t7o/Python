import type { DashboardLayout } from '@/lib/types'

export function prettyDashboardLayout(layout: DashboardLayout): string {
  return JSON.stringify(layout, null, 2)
}

export function parseDashboardLayout(text: string): DashboardLayout {
  return JSON.parse(text) as DashboardLayout
}

export function downloadDashboardJson(name: string, layout: DashboardLayout) {
  const blob = new Blob([prettyDashboardLayout(layout)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${name || 'dashboard'}.json`
  document.body.appendChild(a)
  a.click()
  a.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function readDashboardJson(file: File): Promise<DashboardLayout> {
  return parseDashboardLayout(await file.text())
}
