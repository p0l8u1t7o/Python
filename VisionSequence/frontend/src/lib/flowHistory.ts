export interface HistoryState<T> {
  past: T[]
  future: T[]
  limit: number
}

export interface HistoryStep<T> {
  state: HistoryState<T>
  value: T | null
}

export function createHistory<T>(limit = 50): HistoryState<T> {
  return { past: [], future: [], limit: Math.max(1, limit) }
}

export function pushHistory<T>(state: HistoryState<T>, value: T): HistoryState<T> {
  const past = [...state.past, value].slice(-state.limit)
  return { ...state, past, future: [] }
}

export function undoHistory<T>(state: HistoryState<T>, current: T): HistoryStep<T> {
  if (state.past.length === 0) return { state, value: null }
  const value = state.past[state.past.length - 1]
  return {
    state: {
      ...state,
      past: state.past.slice(0, -1),
      future: [current, ...state.future].slice(0, state.limit),
    },
    value,
  }
}

export function redoHistory<T>(state: HistoryState<T>, current: T): HistoryStep<T> {
  if (state.future.length === 0) return { state, value: null }
  const value = state.future[0]
  return {
    state: {
      ...state,
      past: [...state.past, current].slice(-state.limit),
      future: state.future.slice(1),
    },
    value,
  }
}
