/** 主動提示：規則配對、冷卻、關閉紀錄。 */
import { beforeEach, describe, expect, it } from 'vitest'

import type { ActivityEvent } from '@/lib/activity'
import { dismissHint, hintFor, resetHints, shouldShow } from '@/lib/hints'

const ev = (kind: ActivityEvent['kind'], text: string, detail = ''): ActivityEvent => ({ at: Date.now(), kind, text, detail, route: '/x', count: 1 })

describe('hints', () => {
  beforeEach(() => {
    sessionStorage.clear()
    resetHints()
  })

  it('matches known failures and ignores the rest', () => {
    expect(hintFor(ev('error', 'POST /vision/flows/1/run -> 423 engine_locked'))?.key).toBe('locked')
    expect(hintFor(ev('error', 'PATCH /vision/flows/1 -> 403 teach_only'))?.key).toBe('permission')
    expect(hintFor(ev('error', 'POST /comm/connections/test -> 422 connection_failed', 'Nothing is listening at 127.0.0.1:9001'))?.key).toBe('receiver')
    expect(hintFor(ev('error', 'POST /vision/flows/1/preview -> 422 no_source'))?.key).toBe('noSource')
    expect(hintFor(ev('warning', 'Address already in use: 0.0.0.0:502'))?.key).toBe('portInUse')
    expect(hintFor(ev('error', 'POST /vision/flows/1/run -> 504 run_timeout'))?.key).toBe('timeout')
    expect(hintFor(ev('error', 'GET /vision/flows -> 500 internal'))?.key).toBe('serverError')
    expect(hintFor(ev('run', 'preview flow 3: failed', 'blob: failed (bad input)'))?.key).toBe('runFailed')
    expect(hintFor(ev('run', 'preview flow 3: ok'))).toBeNull()
    expect(hintFor(ev('success', 'Saved'))).toBeNull()
    expect(hintFor(ev('nav', '/flows'))).toBeNull()
    expect(hintFor(ev('error', 'POST /vision/x -> 404 not_found'))).toBeNull()
    const hint = hintFor(ev('error', 'POST /vision/flows/1/run -> 423 engine_locked', 'locked by integrator'))
    expect(hint?.question).toContain('423 engine_locked locked by integrator')
    expect(hint?.detail).toBe('locked by integrator')
  })

  it('shows once per cooldown and never after dismissal', () => {
    const hint = hintFor(ev('error', 'x -> 423 engine_locked'))!
    expect(shouldShow(hint, 1_000_000)).toBe(true)
    expect(shouldShow(hint, 1_000_000 + 60_000)).toBe(false)
    expect(shouldShow(hint, 1_000_000 + 6 * 60_000)).toBe(true)
    dismissHint('locked')
    expect(shouldShow(hint, 1_000_000 + 20 * 60_000)).toBe(false)
    expect(shouldShow(hintFor(ev('error', 'x -> 403 forbidden'))!, 1_000_000 + 20 * 60_000)).toBe(true)
  })
})
