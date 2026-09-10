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

export const ACQUIRE_TYPES = new Set(['image_source', 'fixed_image', 'stereo_grab', 'multi_light_grab'])
export const SOURCE_NODE_IDS = new Set(['src', 'source', 'camera', 'grab', 'stereo_grab'])

function asImage(value: unknown): RunImage | null {
  if (value && typeof value === 'object' && 'ref' in value && 'width' in value) {
    const r = value as { ref: string | null; width: number; height: number }
    if (r.ref) return { ref: r.ref, width: r.width, height: r.height }
  }
  return null
}

/** The representative frame: result image when present, otherwise the acquisition frame. */
export function lastImage(run: RunReport, types?: Record<string, string>): RunImage | null {
  const reports = Object.values(run.nodes ?? {})
  for (const [id, report] of Object.entries(run.nodes ?? {})) {
    if (types ? types[id] === 'draw_result' : id === 'draw' || id === 'draw_result') {
      const outputs = report.outputs ?? {}
      for (const key of types ? ['image', ...Object.keys(outputs).filter((key) => key !== '_image')] : Object.keys(outputs)) {
        const value = outputs[key]
        const image = asImage(value)
        if (image) return image
      }
    }
  }
  for (const [id, report] of Object.entries(run.nodes ?? {})) {
    if (types ? ACQUIRE_TYPES.has(types[id]) : SOURCE_NODE_IDS.has(id)) {
      const outputs = report.outputs ?? {}
      for (const key of types ? ['image', ...Object.keys(outputs).filter((key) => key !== '_image')] : Object.keys(outputs).filter((key) => key !== '_image')) {
        const value = outputs[key]
        const image = asImage(value)
        if (image) return image
      }
    }
  }
  for (const skipThru of types ? [true] : [true, false]) {
    for (let i = reports.length - 1; i >= 0; i -= 1) {
      const outputs = reports[i].outputs ?? {}
      for (const key of types ? ['image', ...Object.keys(outputs)] : Object.keys(outputs)) {
        if (skipThru && key === '_image') continue
        const value = outputs[key]
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
