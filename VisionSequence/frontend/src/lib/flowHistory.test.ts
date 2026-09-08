import { describe, expect, it } from 'vitest'

import { createHistory, pushHistory, redoHistory, undoHistory } from './flowHistory'

describe('flowHistory', () => {
  it('pushes items up to the configured limit', () => {
    let state = createHistory<number>(2)
    state = pushHistory(state, 1)
    state = pushHistory(state, 2)
    state = pushHistory(state, 3)
    expect(state.past).toEqual([2, 3])
  })

  it('undoes and redoes with the current value on the opposite stack', () => {
    let state = createHistory<string>(5)
    state = pushHistory(state, 'a')
    state = pushHistory(state, 'b')

    const undone = undoHistory(state, 'c')
    expect(undone.value).toBe('b')
    expect(undone.state.past).toEqual(['a'])
    expect(undone.state.future).toEqual(['c'])

    const redone = redoHistory(undone.state, 'b')
    expect(redone.value).toBe('c')
    expect(redone.state.past).toEqual(['a', 'b'])
    expect(redone.state.future).toEqual([])
  })

  it('clears redo entries after a new edit is pushed', () => {
    let state = createHistory<string>(5)
    state = pushHistory(state, 'a')
    state = undoHistory(state, 'b').state
    expect(state.future).toEqual(['b'])

    state = pushHistory(state, 'x')
    expect(state.past).toEqual(['x'])
    expect(state.future).toEqual([])
  })
})
