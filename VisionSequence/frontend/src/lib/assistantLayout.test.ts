import { beforeEach, describe, expect, it } from 'vitest'

import { assistantLayoutState, resetAssistantLayout, setAssistantLayout, setAssistantOpen } from './assistantLayout'

describe('assistantLayout', () => {
  beforeEach(() => resetAssistantLayout())

  it('defaults to a floating window and remembers the side layout on the device', () => {
    expect(assistantLayoutState()).toEqual({ layout: 'float', open: false })
    setAssistantLayout('side')
    expect(assistantLayoutState().layout).toBe('side')
    expect(localStorage.getItem('vs.assistant.layout')).toBe('side')
    setAssistantOpen(true)
    expect(assistantLayoutState()).toEqual({ layout: 'side', open: true })
    setAssistantLayout('float')
    expect(localStorage.getItem('vs.assistant.layout')).toBe('float')
    resetAssistantLayout()
    expect(localStorage.getItem('vs.assistant.layout')).toBeNull()
  })
})
