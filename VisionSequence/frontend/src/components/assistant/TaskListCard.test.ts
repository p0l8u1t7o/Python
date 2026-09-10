/** 提案的不可變更新與確認狀態。 */
import { describe, expect, it } from 'vitest'
import { confirmDraft, mergeDraft } from './TaskListCard'
import type { TaskDraft } from '@/lib/types'

const draft: TaskDraft = { draft_id: 'd', kind: 'count_objects', op: 'add', fields: {
  min_count: { value: 5, status: 'assumed', source: 'llm', note: 'Confirm' },
  roi: { value: null, status: 'missing', source: 'rule', note: 'Draw' },
}, regions: [] }

describe('task draft', () => {
  it('confirms edited fields without mutating the source or other fields', () => {
    const changed = mergeDraft(draft, 'min_count', 7)
    expect(changed.fields.min_count).toEqual({ value: 7, status: 'confirmed', source: 'user', note: '' })
    expect(changed.fields.roi.status).toBe('missing')
    expect(draft.fields.min_count.status).toBe('assumed')
  })
  it('keeps missing information missing when confirming assumptions', () => {
    const next = confirmDraft(draft)
    expect(next.fields.min_count.status).toBe('confirmed')
    expect(next.fields.roi.status).toBe('missing')
    expect(draft.fields.min_count.status).toBe('assumed')
  })
})
