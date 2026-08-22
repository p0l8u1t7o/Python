import { useEffect, useRef, useState } from 'react'

/**
 * Whether a dialog's form differs from what it opened with.
 *
 * The snapshot is taken one tick after `open` turns true, not in the same
 * render: every edit dialog populates its form from the record in an effect
 * that runs on open, and a snapshot taken before that populate would make
 * every existing record look "edited" the moment it was opened.
 *
 * Comparison is by JSON, which is exactly right for the plain objects these
 * forms keep in state and wrong for anything holding functions or dates -
 * none of the dialogs do.
 */
export function useFormDirty(open: boolean, form: unknown): boolean {
  const [snapshot, setSnapshot] = useState<string | null>(null)
  const latest = useRef(form)
  latest.current = form

  useEffect(() => {
    if (!open) {
      setSnapshot(null)
      return
    }
    const id = window.setTimeout(() => setSnapshot(JSON.stringify(latest.current)), 0)
    return () => window.clearTimeout(id)
  }, [open])

  if (!open || snapshot === null) return false
  return JSON.stringify(form) !== snapshot
}
