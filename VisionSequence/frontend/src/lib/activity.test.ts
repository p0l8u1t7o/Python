/** 操作軌跡：環形緩衝、連續重複合併、金鑰遮罩、分享開關與送出形狀。 */
import { beforeEach, describe, expect, it } from 'vitest'

import { activityPayload, clearActivity, logActivity, recentActivity, redact, setActivityRoute, setShareEnabled, shareEnabled } from '@/lib/activity'

describe('activity trail', () => {
  beforeEach(() => {
    clearActivity()
    localStorage.clear()
    setActivityRoute('/sources')
  })

  it('keeps the latest events, merges consecutive duplicates and tags the route', () => {
    for (let i = 0; i < 45; i++) logActivity('nav', `/page/${i}`)
    expect(recentActivity(100).length).toBe(40)
    logActivity('error', 'POST /vision/sources/test → 422 no_frame', 'nothing there')
    logActivity('error', 'POST /vision/sources/test → 422 no_frame', 'nothing there')
    const last = recentActivity(1)[0]
    expect(last.count).toBe(2)
    expect(last.route).toBe('/sources')
    expect(activityPayload(1)[0]).toMatchObject({ kind: 'error', text: 'POST /vision/sources/test → 422 no_frame', detail: 'nothing there', count: 2 })
    expect(activityPayload(1)[0].ago_s).toBeGreaterThanOrEqual(0)
  })

  it('redacts secrets and ignores empty text', () => {
    expect(redact('Authorization: Bearer abc.def-ghi')).toBe('Authorization: Bearer ***')
    expect(redact('api_key=sk-12345 password: "hunter2"')).toBe('api_key=*** password: "***"')
    expect(redact('sha 0123456789abcdef0123456789abcdef')).toBe('sha ***')
    logActivity('success', '   ')
    expect(recentActivity().length).toBe(0)
  })

  it('remembers the share preference (default on)', () => {
    expect(shareEnabled()).toBe(true)
    setShareEnabled(false)
    expect(shareEnabled()).toBe(false)
    expect(localStorage.getItem('vs.assistant.share')).toBe('0')
  })
})
