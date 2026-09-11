import { describe, expect, it } from 'vitest'

import { PERSIST_KEY, PERSIST_MAX_CHARS, PERSIST_MAX_ENTRIES, clearPersistedDraft, clearSession, getSession, patchDraftNode, persistDraft, persistedDraftMatches, readPersistedDraft, setDraft, updateSession } from '@/lib/flowDraft'

const graph = { nodes: [{ id: 'a', type: 'grayscale', params: { x: 1 } }, { id: 'b', type: 'judge', params: {} }], edges: [{ source: 'a', target: 'b' }] }

describe('flowDraft store', () => {
  it('starts empty and merges patches', () => {
    clearSession(1)
    expect(getSession(1).draft).toBeNull()
    updateSession(1, { reuseImage: true })
    expect(getSession(1).reuseImage).toBe(true)
    expect(getSession(1).scratch).toBeNull()
  })

  it('patchDraftNode only touches the target node and marks dirty', () => {
    setDraft(2, { baseVersion: 3, graph, name: 'f', description: '', dirty: false })
    patchDraftNode(2, 'a', { params: { x: 2 } })
    const d = getSession(2).draft!
    expect(d.dirty).toBe(true)
    expect(d.graph.nodes[0].params).toEqual({ x: 2 })
    expect(d.graph.nodes[1]).toEqual(graph.nodes[1])
    expect(d.baseVersion).toBe(3)
  })

  it('patchDraftNode is a no-op without a draft', () => {
    clearSession(3)
    patchDraftNode(3, 'a', { params: {} })
    expect(getSession(3).draft).toBeNull()
  })
})

describe('flowDraft persistence (reload protection)', () => {
  const draft = { baseVersion: 3, graph, name: 'f', description: 'd', dirty: true }

  it('stores only dirty drafts and reads them back by flow', () => {
    localStorage.removeItem(PERSIST_KEY)
    expect(persistDraft(5, { ...draft, dirty: false })).toBe(false)
    expect(readPersistedDraft(5)).toBeNull()
    expect(persistDraft(5, draft, new Date('2026-01-02T03:04:05Z'))).toBe(true)
    const stored = readPersistedDraft(5)!
    expect(stored.graph).toEqual(graph)
    expect(stored.baseVersion).toBe(3)
    expect(stored.savedAt).toBe('2026-01-02T03:04:05.000Z')
    clearPersistedDraft(5)
    expect(readPersistedDraft(5)).toBeNull()
    expect(localStorage.getItem(PERSIST_KEY)).toBeNull()
  })

  it('keeps the newest entries and refuses oversized drafts', () => {
    localStorage.removeItem(PERSIST_KEY)
    for (let i = 1; i <= PERSIST_MAX_ENTRIES + 2; i += 1) persistDraft(i, draft, new Date(Date.UTC(2026, 0, i)))
    expect(readPersistedDraft(1)).toBeNull()
    expect(readPersistedDraft(2)).toBeNull()
    expect(readPersistedDraft(PERSIST_MAX_ENTRIES + 2)).not.toBeNull()
    const huge = { ...draft, graph: { nodes: [{ id: 'a', type: 'note', params: { text: 'x'.repeat(PERSIST_MAX_CHARS) } }], edges: [] } }
    expect(persistDraft(99, huge)).toBe(false)
    expect(readPersistedDraft(99)).toBeNull()
    localStorage.setItem(PERSIST_KEY, '{broken')
    expect(readPersistedDraft(3)).toBeNull()
    localStorage.removeItem(PERSIST_KEY)
  })

  it('matches only the same version saved at the same time', () => {
    // 改描述、改設定不會 +1 version，所以還要比 updated_at；舊草稿沒記 updated_at 就只比版本
    localStorage.removeItem(PERSIST_KEY)
    persistDraft(7, draft, new Date(), '2026-01-01T00:00:00Z')
    const stored = readPersistedDraft(7)!
    expect(persistedDraftMatches(stored, { version: 3, updated_at: '2026-01-01T00:00:00Z' })).toBe(true)
    expect(persistedDraftMatches(stored, { version: 3, updated_at: '2026-01-01T00:00:05Z' })).toBe(false)
    expect(persistedDraftMatches(stored, { version: 4, updated_at: '2026-01-01T00:00:00Z' })).toBe(false)
    expect(persistedDraftMatches({ ...stored, baseUpdatedAt: undefined }, { version: 3, updated_at: 'anything' })).toBe(true)
    localStorage.removeItem(PERSIST_KEY)
  })
})
