import { describe, expect, it } from 'vitest'

import { auditChanges, formatAuditValue } from '@/lib/auditDetail'

describe('auditChanges', () => {
  it('turns graph parameter diffs into rows and keeps the counts aside', () => {
    const view = auditChanges({ params: [{ node: 'thr', type: 'threshold', param: 'threshold', before: 60, after: 46 }], count: 1, added: ['gray'] })
    expect(view.rows).toEqual([{ label: 'thr · threshold', before: 60, after: 46 }])
    expect(view.rest).toEqual({ added: ['gray'] })
  })

  it('reads field diffs and change lists', () => {
    expect(auditChanges({ is_enabled: { before: true, after: false }, note: 'x' }).rows).toEqual([{ label: 'is_enabled', before: true, after: false }])
    expect(auditChanges({ changes: [{ field: 'role', before: 'operator', after: 'engineer' }] })).toEqual({ rows: [{ label: 'role', before: 'operator', after: 'engineer' }], rest: null })
    expect(auditChanges({})).toEqual({ rows: [], rest: null })
    expect(auditChanges(null)).toEqual({ rows: [], rest: null })
  })

  it('formats values without Python repr', () => {
    expect(formatAuditValue(null)).toBe('—')
    expect(formatAuditValue(true)).toBe('true')
    expect(formatAuditValue([{ id: 'a' }])).toBe('[{"id":"a"}]')
    expect(formatAuditValue('x'.repeat(200), 20)).toHaveLength(20)
  })
})
