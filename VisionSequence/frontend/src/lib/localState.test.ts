/** 登出清掉使用者層的本機狀態，裝置層保留。 */
import { describe, expect, it } from 'vitest'

import { clearUserState, DEVICE_SCOPED_KEYS, USER_SCOPED_KEYS } from '@/lib/localState'

describe('clearUserState', () => {
  it('removes user-scoped keys and keeps device-scoped ones', () => {
    for (const k of [...USER_SCOPED_KEYS, ...DEVICE_SCOPED_KEYS]) localStorage.setItem(k, 'x')
    sessionStorage.setItem('vs.assistant.hints.dismissed', '["locked"]')
    clearUserState()
    for (const k of USER_SCOPED_KEYS) expect(localStorage.getItem(k), k).toBeNull()
    for (const k of DEVICE_SCOPED_KEYS) expect(localStorage.getItem(k), k).toBe('x')
    expect(sessionStorage.getItem('vs.assistant.hints.dismissed')).toBeNull()
  })
})
