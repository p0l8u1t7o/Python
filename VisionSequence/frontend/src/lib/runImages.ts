/**
 * Picking the picture to show for a run.
 *
 * A run's representative picture follows the board rule: configured callers can pick a node; the
 * generic fallback prefers an explicit result image and otherwise uses the acquisition frame.
 * The implicit `_image` pass-through port is only used when a run has nothing else.
 */
import type { RunReport } from '@/lib/types'

export interface RunImage {
  ref: string
  width: number
  height: number
}

const SOURCE_NODE_IDS = new Set(['src', 'source', 'camera', 'grab', 'stereo_grab'])

function asImage(value: unknown): RunImage | null {
  if (value && typeof value === 'object' && 'ref' in value && 'width' in value) {
    const r = value as { ref: string | null; width: number; height: number }
    if (r.ref) return { ref: r.ref, width: r.width, height: r.height }
  }
  return null
}

/** The representative frame: result image when present, otherwise the acquisition frame. */
export function lastImage(run: RunReport): RunImage | null {
  const reports = Object.values(run.nodes ?? {})
  for (const [id, report] of Object.entries(run.nodes ?? {})) {
    if (id === 'draw' || id === 'draw_result') {
      for (const value of Object.values(report.outputs ?? {})) {
        const image = asImage(value)
        if (image) return image
      }
    }
  }
  for (const [id, report] of Object.entries(run.nodes ?? {})) {
    if (SOURCE_NODE_IDS.has(id)) {
      for (const [key, value] of Object.entries(report.outputs ?? {})) {
        if (key === '_image') continue
        const image = asImage(value)
        if (image) return image
      }
    }
  }
  for (const skipThru of [true, false]) {
    for (let i = reports.length - 1; i >= 0; i -= 1) {
      for (const [key, value] of Object.entries(reports[i].outputs ?? {})) {
        if (skipThru && key === '_image') continue
        const image = asImage(value)
        if (image) return image
      }
    }
  }
  return null
}

/** The frame that came off the camera: first real image output. */
export function firstImageOutput(run: RunReport): RunImage | null {
  for (const report of Object.values(run.nodes ?? {})) {
    for (const [key, value] of Object.entries(report.outputs ?? {})) {
      if (key === '_image') continue
      const image = asImage(value)
      if (image) return image
    }
  }
  return null
}
