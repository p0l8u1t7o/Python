/**
 * 標定摘要：後端 `calib.summary_parts()` 給每一塊的數字，這裡依介面語言組成一句（L-4）。
 * 舊資產只有英文 `summary` 時原樣顯示。
 */
import type { TFunction } from 'i18next'

export interface CalibrationSummaryPart {
  kind: 'lens' | 'world' | 'robot' | 'mapping' | 'stereo' | string
  [key: string]: unknown
}

export interface CalibrationSummaryMeta {
  summary?: string
  summary_parts?: CalibrationSummaryPart[]
}

function num(value: unknown, digits: number): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—'
}

function mode(t: TFunction, value: unknown): string {
  const key = typeof value === 'string' ? value : ''
  return key ? t(`calibration.summaryParts.modes.${key}`, { defaultValue: key }) : ''
}

/** 來源名稱；沒填或還是後端預設的 camera A／B 就用介面語言的字。 */
function named(t: TFunction, value: unknown, fallback: string): string {
  return typeof value === 'string' && value && !/^camera [ab]$/i.test(value) ? value : t(fallback)
}

function yesNo(t: TFunction, value: unknown): string {
  return t(value ? 'calibration.summaryParts.yes' : 'calibration.summaryParts.no')
}

export function calibrationSummary(meta: CalibrationSummaryMeta | null | undefined, t: TFunction): string {
  const parts = meta?.summary_parts
  if (!Array.isArray(parts)) return meta?.summary ?? ''
  const bits: string[] = []
  for (const part of parts) {
    switch (part.kind) {
      case 'lens':
        bits.push(t('calibration.summaryParts.lens', { views: part.views, rms: num(part.rms, 2) }))
        break
      case 'world':
        bits.push(t('calibration.summaryParts.world', { mode: mode(t, part.mode), scale: num(part.scale, 5), unit: part.unit }))
        if (typeof part.rms === 'number') bits.push(t('calibration.summaryParts.worldFit', { rms: num(part.rms, 3), unit: part.unit }))
        break
      case 'robot':
        bits.push(t('calibration.summaryParts.robot', {
          mode: mode(t, part.mode), points: part.points, rms: num(part.rms, 3), max: num(part.max, 3), unit: part.unit,
          handedness: t(`calibration.summaryParts.handed.${part.handedness === 'left' ? 'left' : 'right'}`), center: yesNo(t, part.rotation_center),
        }))
        if (typeof part.rotation_points === 'number') {
          bits.push(t('calibration.summaryParts.robotRotation', { points: part.rotation_points, rms: num(part.rotation_rms, 3), max: num(part.rotation_max, 3) }))
        }
        break
      case 'mapping':
        bits.push(t('calibration.summaryParts.mapping', {
          from: named(t, part.from, 'calibration.summaryParts.cameraA'), to: named(t, part.to, 'calibration.summaryParts.cameraB'),
          mode: mode(t, part.mode), points: part.points, rms: num(part.rms, 3), max: num(part.max, 3),
        }))
        break
      case 'stereo':
        bits.push(t('calibration.summaryParts.stereo', { baseline: num(part.baseline, 3), rms: num(part.rms, 3) }))
        if (part.z_ref) bits.push(t('calibration.summaryParts.zRef'))
        break
      default:
        break
    }
  }
  return bits.length ? bits.join(t('calibration.summaryParts.join')) : (meta?.summary ?? t('calibration.summaryParts.empty'))
}
