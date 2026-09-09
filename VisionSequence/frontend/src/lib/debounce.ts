export interface TimerScheduler {
  setTimeout: (handler: () => void, delayMs: number) => number
  clearTimeout: (handle: number) => void
}

export interface DebouncedCall<T extends unknown[]> {
  schedule: (...args: T) => void
  cancel: () => void
}

export function createDebouncedCall<T extends unknown[]>(
  fn: (...args: T) => void,
  delayMs: number,
  scheduler: TimerScheduler = window,
): DebouncedCall<T> {
  let timer: number | undefined
  return {
    schedule: (...args: T) => {
      if (timer !== undefined) scheduler.clearTimeout(timer)
      timer = scheduler.setTimeout(() => {
        timer = undefined
        fn(...args)
      }, delayMs)
    },
    cancel: () => {
      if (timer === undefined) return
      scheduler.clearTimeout(timer)
      timer = undefined
    },
  }
}
