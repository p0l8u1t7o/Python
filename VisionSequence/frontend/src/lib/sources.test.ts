/** 影像來源清單摘要：設定挑重點欄位、狀態轉徽章。 */
import { describe, expect, it } from 'vitest'

import { sourceStatus, summarizeSourceConfig } from '@/lib/sources'

describe('summarizeSourceConfig', () => {
  it('picks path / size / pattern in a stable order and caps at three parts', () => {
    expect(summarizeSourceConfig('folder', { path: 'data\\samples\\stop_signs', loop: true, sort: 'name' })).toBe('data\\samples\\stop_signs · loop: on · sort: name')
    expect(summarizeSourceConfig('synthetic', { width: 1280, height: 960, pattern: 'parts', seed: 7, defect_rate: 0.3 })).toBe('1280×960 · pattern: parts · seed: 7')
    expect(summarizeSourceConfig('camera', {})).toBe('camera')
    expect(summarizeSourceConfig('x', { foo: 'bar', empty: '' })).toBe('foo: bar')
  })

  it('shortens long paths from the tail', () => {
    const s = summarizeSourceConfig('folder', { path: 'D:\\Working Space\\Python\\VisionSequence\\data\\assets\\dl\\weights\\bus.jpg' })
    expect(s.startsWith('…')).toBe(true)
    expect(s.endsWith('bus.jpg')).toBe(true)
    expect(s.length).toBeLessThan(45)
  })
})

describe('sourceStatus', () => {
  it('maps open / closed / error with frame counts', () => {
    expect(sourceStatus({ open: true, kind: 'folder', frames: 4 })).toEqual({ tone: 'ok', key: 'statusOpen', frames: 4, error: '' })
    expect(sourceStatus({ open: false })).toEqual({ tone: 'neutral', key: 'statusClosed', frames: null, error: '' })
    expect(sourceStatus({ open: true, error: 'timeout' }).tone).toBe('critical')
    expect(sourceStatus(null).key).toBe('statusClosed')
  })
})
