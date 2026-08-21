/**
 * A glossary term with an explanation bubble.
 *
 *     <Term id="soc" />                    // renders the localised name
 *     <Term id="soc">{t('storage.soc')}</Term>   // wraps existing text
 *
 * Three interaction models, because the console is used on all three:
 *
 * - **Mouse**: hover with a short delay, so sweeping the pointer across a
 *   table header row does not fire a burst of bubbles.
 * - **Touch**: tap to open, tap anywhere else to close. Phones have no hover
 *   at all, so a hover-only tooltip is simply invisible on a phone - and this
 *   console does get opened on one.
 * - **Keyboard**: the trigger is a real `<button>`, so Tab reaches it and
 *   Enter/Space work for free. Escape closes.
 *
 * The bubble renders into a portal on `document.body` with fixed positioning.
 * That is not over-engineering: the terms sit inside `Table` (which wraps its
 * contents in `overflow-x-auto`) and inside cards, and any ancestor with
 * `overflow` other than visible clips an absolutely positioned child no matter
 * what z-index it is given.
 */

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

import { normalizeLanguage } from '@/i18n'
import { resolveTerm, termHeading, type GlossaryId } from '@/lib/glossary'

/** Milliseconds the pointer must rest before a bubble appears. */
const HOVER_OPEN_DELAY = 350
/** Grace period so moving the pointer from the word onto the bubble is allowed. */
const HOVER_CLOSE_DELAY = 120
const BUBBLE_WIDTH = 300
const VIEWPORT_MARGIN = 8
const GAP = 8

// ---------------------------------------------------------------------------
// "Only one bubble at a time" - a module-level store rather than a provider,
// so <Term> works anywhere without the caller having to wrap anything.
// ---------------------------------------------------------------------------
let openTermKey: string | null = null
const listeners = new Set<() => void>()

function setOpenTerm(key: string | null): void {
  if (openTermKey === key) return
  openTermKey = key
  listeners.forEach((listener) => listener())
}

function useIsOpen(key: string): boolean {
  const [open, setOpen] = useState(() => openTermKey === key)
  useEffect(() => {
    const listener = () => setOpen(openTermKey === key)
    listeners.add(listener)
    listener()
    return () => {
      listeners.delete(listener)
    }
  }, [key])
  return open
}

// ---------------------------------------------------------------------------
// Trigger
// ---------------------------------------------------------------------------
export function Term({
  id,
  children,
  className = '',
}: {
  id: GlossaryId
  children?: React.ReactNode
  className?: string
}) {
  // Reading i18n.language rather than calling currentLanguage() is what makes
  // an open bubble follow a language switch: useTranslation re-renders on the
  // change, and the language is then a real input to the lookup.
  const { i18n } = useTranslation()
  const key = useId()
  const open = useIsOpen(key)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const openTimer = useRef<number | undefined>(undefined)
  const closeTimer = useRef<number | undefined>(undefined)
  // A click focuses the button too; without this the focus handler would
  // re-open the bubble the click just closed.
  const pointerActivated = useRef(false)

  const term = resolveTerm(id, normalizeLanguage(i18n.language))

  const clearTimers = useCallback(() => {
    window.clearTimeout(openTimer.current)
    window.clearTimeout(closeTimer.current)
  }, [])

  useEffect(
    () => () => {
      clearTimers()
      // Navigating away with a bubble open would otherwise leave the store
      // pointing at a term that no longer exists, and the next term to open
      // would be the second one the user asked for.
      if (openTermKey === key) setOpenTerm(null)
    },
    [clearTimers, key],
  )

  const show = useCallback(() => {
    clearTimers()
    setOpenTerm(key)
  }, [clearTimers, key])

  const hide = useCallback(() => {
    clearTimers()
    setOpenTerm(null)
  }, [clearTimers])

  // ---- mouse ----
  const handlePointerEnter = (event: React.PointerEvent) => {
    if (event.pointerType !== 'mouse') return
    clearTimers()
    openTimer.current = window.setTimeout(() => setOpenTerm(key), HOVER_OPEN_DELAY)
  }

  const handlePointerLeave = (event: React.PointerEvent) => {
    if (event.pointerType !== 'mouse') return
    clearTimers()
    closeTimer.current = window.setTimeout(hide, HOVER_CLOSE_DELAY)
  }

  // ---- touch and click ----
  const handlePointerDown = () => {
    pointerActivated.current = true
  }

  const handleClick = () => {
    if (open) hide()
    else show()
  }

  // ---- keyboard ----
  const handleFocus = () => {
    if (pointerActivated.current) {
      pointerActivated.current = false
      return
    }
    show()
  }

  const handleBlur = () => {
    pointerActivated.current = false
    hide()
  }

  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        // aria-describedby is what makes a screen reader announce the
        // definition as description rather than as a separate control.
        aria-describedby={open ? `${key}-bubble` : undefined}
        aria-expanded={open}
        onPointerEnter={handlePointerEnter}
        onPointerLeave={handlePointerLeave}
        onPointerDown={handlePointerDown}
        onClick={handleClick}
        onFocus={handleFocus}
        onBlur={handleBlur}
        // Inherit everything from the surrounding text: the marker has to read
        // as an annotation on a label, not as a button sitting in a table
        // header. The base stylesheet already supplies the focus ring.
        className={`cursor-help border-0 bg-transparent p-0 text-left font-[inherit] text-[inherit] leading-[inherit] underline decoration-dotted decoration-from-font underline-offset-4 hover:decoration-solid ${className}`}
      >
        {children ?? term.label}
      </button>
      {open ? (
        <TermBubble
          bubbleId={`${key}-bubble`}
          anchor={triggerRef}
          onDismiss={hide}
          onPointerEnter={clearTimers}
          onPointerLeave={hide}
          heading={termHeading(term)}
          subheading={term.abbr ? term.label : undefined}
          definition={term.definition}
        />
      ) : null}
    </>
  )
}

// ---------------------------------------------------------------------------
// Bubble
// ---------------------------------------------------------------------------
interface Position {
  top: number
  left: number
  placement: 'top' | 'bottom'
  arrowLeft: number
}

function TermBubble({
  bubbleId,
  anchor,
  onDismiss,
  onPointerEnter,
  onPointerLeave,
  heading,
  subheading,
  definition,
}: {
  bubbleId: string
  anchor: React.RefObject<HTMLElement | null>
  onDismiss: () => void
  onPointerEnter: () => void
  onPointerLeave: () => void
  heading: string
  subheading?: string
  definition: string
}) {
  const bubbleRef = useRef<HTMLDivElement | null>(null)
  const [position, setPosition] = useState<Position | null>(null)

  // useLayoutEffect so the first paint is already in the right place; with a
  // plain effect the bubble visibly jumps from the top-left corner.
  useLayoutEffect(() => {
    const place = () => {
      const trigger = anchor.current
      const bubble = bubbleRef.current
      if (!trigger || !bubble) return

      const rect = trigger.getBoundingClientRect()
      const height = bubble.offsetHeight
      const width = bubble.offsetWidth

      // Flip above when there is not enough room below - and only if there is
      // actually more room above, so a cramped viewport does not flip into an
      // even worse position.
      const spaceBelow = window.innerHeight - rect.bottom
      const spaceAbove = rect.top
      const placement: Position['placement'] =
        spaceBelow < height + GAP + VIEWPORT_MARGIN && spaceAbove > spaceBelow ? 'top' : 'bottom'

      const top = placement === 'bottom' ? rect.bottom + GAP : rect.top - height - GAP

      // Centre on the trigger, then clamp so a term near either edge is never
      // cut off. The arrow stays over the word even after clamping.
      const centred = rect.left + rect.width / 2 - width / 2
      const left = Math.min(
        Math.max(VIEWPORT_MARGIN, centred),
        Math.max(VIEWPORT_MARGIN, window.innerWidth - width - VIEWPORT_MARGIN),
      )
      const arrowLeft = Math.min(
        Math.max(12, rect.left + rect.width / 2 - left),
        Math.max(12, width - 12),
      )

      setPosition({ top, left, placement, arrowLeft })
    }

    place()
    // One frame later as well: fonts and wrapping can change the height after
    // the first measurement, which would leave a flipped bubble misplaced.
    const frame = window.requestAnimationFrame(place)
    return () => window.cancelAnimationFrame(frame)
  }, [anchor, definition])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onDismiss()
    }
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null
      if (bubbleRef.current?.contains(target ?? null)) return
      if (anchor.current?.contains(target ?? null)) return // the trigger toggles itself
      onDismiss()
    }
    // Closing on scroll beats trying to follow the anchor: the bubble is
    // fixed-positioned, so a scrolled page would leave it pointing at nothing.
    const onScroll = () => onDismiss()

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('pointerdown', onPointerDown, true)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', onScroll)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('pointerdown', onPointerDown, true)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', onScroll)
    }
  }, [anchor, onDismiss])

  return createPortal(
    <div
      ref={bubbleRef}
      id={bubbleId}
      role="tooltip"
      onPointerEnter={onPointerEnter}
      onPointerLeave={onPointerLeave}
      style={{
        position: 'fixed',
        top: position?.top ?? 0,
        left: position?.left ?? 0,
        width: Math.min(BUBBLE_WIDTH, window.innerWidth - VIEWPORT_MARGIN * 2),
        // Above the modal (z-50) so terms inside a dialog still work, below
        // toasts (z-100) so a notification is never covered by a tooltip.
        zIndex: 90,
        // Hidden until measured, so it never flashes in the corner.
        visibility: position ? 'visible' : 'hidden',
      }}
      className="rounded-lg border border-line-strong bg-surface p-3 shadow-lg"
    >
      <p className="text-xs font-semibold text-content">{heading}</p>
      {subheading ? <p className="mt-0.5 text-xs text-muted">{subheading}</p> : null}
      <p className="mt-1.5 text-xs leading-relaxed text-muted">{definition}</p>
      {position ? (
        <span
          aria-hidden
          style={{
            left: position.arrowLeft,
            // Only the two outward-facing edges get a border, so the diamond
            // reads as a continuation of the bubble rather than a floating box.
            ...(position.placement === 'bottom'
              ? {
                  top: -5,
                  borderTop: '1px solid var(--border-strong)',
                  borderLeft: '1px solid var(--border-strong)',
                }
              : {
                  bottom: -5,
                  borderBottom: '1px solid var(--border-strong)',
                  borderRight: '1px solid var(--border-strong)',
                }),
          }}
          className="absolute size-2 -translate-x-1/2 rotate-45 bg-surface"
        />
      ) : null}
    </div>,
    document.body,
  )
}
