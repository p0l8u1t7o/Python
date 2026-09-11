import i18next from 'i18next'
import { describe, expect, it } from 'vitest'

import { calibrationSummary } from '@/lib/calibrationSummary'
import { setLanguage } from '@/i18n'

describe('calibrationSummary', () => {
  it('builds the same English sentence as the backend from the structured parts', async () => {
    await setLanguage('en')
    const text = calibrationSummary({
      summary: 'ignored', summary_parts: [
        { kind: 'lens', views: 5, rms: 0.123 },
        { kind: 'world', mode: 'scale', scale: 0.05, unit: 'mm' },
        { kind: 'mapping', from: 'camera A', to: '', mode: 'affine', points: 4, rms: 0.0001, max: 0.0002 },
        { kind: 'stereo', baseline: 60, rms: 0.1, z_ref: true },
      ],
    }, i18next.t)
    expect(text).toBe('lens 5 views, error 0.12 px; scale 0.05000 mm/px; camera A to camera B affine, 4 points, RMS 0.000 px, max 0.000 px; stereo baseline 60.000 mm, RMS 0.100 px; height reference set')
  })

  it('falls back to the stored text for old assets and translates the parts', async () => {
    expect(calibrationSummary({ summary: 'legacy text' }, i18next.t)).toBe('legacy text')
    await setLanguage('zh-Hant')
    const text = calibrationSummary({ summary_parts: [{ kind: 'world', mode: 'scale', scale: 0.05, unit: 'mm', rms: 0.01 }] }, i18next.t)
    expect(text).toContain('比例')
    expect(text).not.toMatch(/scale|fit/)
    await setLanguage('en')
  })
})
