/** 簡單的滑鼠拖曳分隔線：回傳 onMouseDown，拖曳時呼叫 onChange(delta)。 */
import { useCallback, useRef } from 'react'

export function useResizer(axis: 'x' | 'y', onChange: (delta: number) => void) {
  const handler = useRef(onChange)
  handler.current = onChange
  return useCallback(
    (event: React.MouseEvent) => {
      event.preventDefault()
      let last = axis === 'x' ? event.clientX : event.clientY
      const cursor = axis === 'x' ? 'col-resize' : 'row-resize'
      document.body.style.cursor = cursor
      document.body.style.userSelect = 'none'
      const onMove = (e: MouseEvent) => {
        const now = axis === 'x' ? e.clientX : e.clientY
        handler.current(now - last)
        last = now
      }
      const onUp = () => {
        document.removeEventListener('mousemove', onMove)
        document.removeEventListener('mouseup', onUp)
        document.body.style.cursor = ''
        document.body.style.userSelect = ''
      }
      document.addEventListener('mousemove', onMove)
      document.addEventListener('mouseup', onUp)
    },
    [axis],
  )
}
