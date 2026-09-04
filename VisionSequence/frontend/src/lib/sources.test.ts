/** 影像來源清單摘要：設定挑重點欄位、狀態轉徽章。 */
import { describe, expect, it } from 'vitest'

import { sourceStatus, summarizeSourceConfig } from '@/lib/sources'

describe('summarizeSourceConfig', () => {
  it('picks path / size / pattern in a stable order and caps at three parts', () => {
    expect(summarizeSourceConfig('folder', { path: 'data\\samples\\stop_signs', loop: true, sort: 'name' })).toBe('data\\samples\\stop_signs · loop: on · sort: name')
    expect(summarizeSourceConfig('synthetic', { width: 1280, height: 960, pattern: 'parts', seed: 7, defect_rate: 0.3 })).toBe('1280×960 · pattern: parts · seed: 7')
    expect(summarizeSourceConfig('camera', {})).toBe('camera')
    expect(summarizeSourceConfig('x', { foo: 'bar', empty: '' })).toBe('foo: bar')
    expect(summarizeSourceConfig('capture', { client: 'line-pc', channel: 'cam1', mode: 'on_demand', timeout_ms: 1000 })).toBe('client: line-pc · channel: cam1 · mode: on_demand')
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
    expect(sourceStatus({ open: true, kind: 'folder', frames: 4 })).toMatchObject({ tone: 'ok', key: 'statusOpen', frames: 4, error: '', fps: null, ageMs: null, shm: false })
    expect(sourceStatus({ open: false })).toMatchObject({ tone: 'neutral', key: 'statusClosed', frames: null, error: '' })
    expect(sourceStatus({ open: true, error: 'timeout' }).tone).toBe('critical')
    expect(sourceStatus(null).key).toBe('statusClosed')
    // 擷取端相機：fps／最近影格／共享記憶體；離線優先於舊錯誤
    expect(sourceStatus({ open: true, connected: true, fps: 9.52, age_ms: 120.4, shm: true })).toMatchObject({ tone: 'ok', key: 'statusOpen', fps: 9.5, ageMs: 120, shm: true })
    expect(sourceStatus({ open: false, connected: true, fps: 0, age_ms: null })).toMatchObject({ tone: 'ok', key: 'statusOnline', fps: null, ageMs: null })
    expect(sourceStatus({ open: false, connected: false, last_error: '擷取端「x」未連線' })).toMatchObject({ tone: 'warning', key: 'statusOffline', error: '' })
  })
})
