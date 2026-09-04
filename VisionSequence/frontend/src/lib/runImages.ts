/**
 * Picking the picture to show for a run.
 *
 * Node reports are written in execution order, so the last real image output is the "result" and the
 * first is the frame that came off the camera. The implicit `_image` pass-through port is only used
 * when a run has nothing else — it is the untouched input, not a result.
 */
import type { RunReport } from '@/lib/types'

export interface RunImage {
  ref: string
  width: number
  height: number
}

function asImage(value: unknown): RunImage | null {
  if (value && typeof value === 'object' && 'ref' in value && 'width' in value) {
    const r = value as { ref: string | null; width: number; height: number }
    if (r.ref) return { ref: r.ref, width: r.width, height: r.height }
  }
  return null
}

/** The result frame: last real image output, falling back to the pass-through port. */
export function lastImage(run: RunReport): RunImage | null {
  const reports = Object.values(run.nodes ?? {})
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
