import { Handle, NodeResizer, Position, type NodeProps } from '@xyflow/react'
import * as icons from 'lucide-react'
import { useTranslation } from 'react-i18next'

import type { NodeHandle, NodeTypeDef } from '@/lib/workflowTypes'

/** Colour per output meaning, so a branch is readable without opening it. */
const TONE_CLASS: Record<NodeHandle['tone'], string> = {
  neutral: '!bg-muted',
  ok: '!bg-ok',
  warn: '!bg-warning',
  critical: '!bg-critical',
}

export interface WorkflowNodeData extends Record<string, unknown> {
  definition?: NodeTypeDef
  label: string
  description: string
  enabled: boolean
  breakpoint?: boolean
  /** Custom card colour; empty means the theme's surface. */
  color?: string
  params: Record<string, unknown>
  /** Set while a run has a branch sitting here. */
  active?: boolean
  /** Set when the node's parameters fail validation. */
  problem?: string
  /** Set when the last run failed at this node. */
  errored?: boolean
}

/**
 * Black or near-white, whichever reads on `hex`. YIQ-weighted so a saturated
 * yellow gets dark text and a navy gets light, matching what eyes expect.
 */
export function contrastText(hex: string): string {
  const match = /^#?([0-9a-f]{6})$/i.exec(hex.trim())
  if (!match) return ''
  const value = parseInt(match[1], 16)
  const r = value >> 16
  const g = (value >> 8) & 255
  const b = value & 255
  return (r * 299 + g * 587 + b * 114) / 1000 >= 145 ? '#0f172a' : '#f8fafc'
}

/**
 * One step on the canvas.
 *
 * Reads as a small card rather than a labelled box: the operator's own name is
 * the headline, the node type is the subtitle, and the outputs are labelled
 * where they leave. A canvas whose nodes all say "IF-End" cannot be understood
 * without opening every one of them.
 *
 * A branch currently sitting here is shown as a spinning loading ring (the
 * Node Status Indicator pattern) rather than a coloured border - a border
 * looked too much like selection, and "selected" and "executing" are answers
 * to different questions.
 */
export function WorkflowNode({ data, selected }: NodeProps) {
  const { t } = useTranslation()
  const node = data as WorkflowNodeData
  const definition = node.definition
  const handles = definition?.handles ?? []

  const Icon =
    (definition?.icon && (icons as unknown as Record<string, icons.LucideIcon>)[definition.icon]) ||
    icons.Box

  const hasInput = definition?.key !== 'start'
  const typeLabel = definition
    ? t(`workflows.nodeTypes.${definition.key}.label`, { defaultValue: definition.label })
    : t('workflows.unknownNodeType')

  const customBg = node.color && contrastText(node.color) ? node.color : ''
  const fg = customBg ? contrastText(customBg) : ''

  // Selection wins - it answers "what am I editing" - then a failed run, then
  // a validation problem. The executing state is the loading ring, not a
  // border, so it never competes with these.
  const border = selected
    ? 'border-brand ring-2 ring-brand/35 shadow-lg shadow-brand/10'
    : node.errored
      ? 'border-critical ring-2 ring-critical/30'
      : node.problem
        ? 'border-critical'
        : customBg
          ? 'border-transparent'
          : 'border-line'

  return (
    <div
      className={`min-w-[190px] max-w-[260px] rounded-lg border-2 shadow-sm transition
        ${customBg ? '' : 'bg-surface'}
        ${border}
        ${node.enabled === false ? 'border-dashed opacity-55' : ''}
        ${node.active ? 'zqs-node-loading' : ''}`}
      style={customBg ? { background: customBg, color: fg } : undefined}
    >
      {hasInput ? (
        <Handle type="target" position={Position.Top} className="!size-2 !bg-muted" />
      ) : null}

      <div className="flex items-start gap-2 px-3 pt-2">
        <span
          className={`mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md ${
            customBg ? '' : 'bg-brand-soft text-brand'
          }`}
          style={customBg ? { background: 'rgb(255 255 255 / 0.18)', color: fg } : undefined}
        >
          <Icon size={14} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">
            {node.label || typeLabel}
          </p>
          <p
            className={`truncate text-[11px] ${customBg ? 'opacity-75' : 'text-muted'}`}
          >
            {typeLabel}
          </p>
        </div>
        {node.breakpoint ? (
          <span
            className="mt-1 size-2.5 shrink-0 rounded-full border border-critical bg-critical/80"
            title={t('workflows.breakpoint')}
          />
        ) : null}
        {node.enabled === false ? (
          <icons.PowerOff
            size={13}
            aria-hidden
            className={`mt-0.5 shrink-0 ${customBg ? 'opacity-75' : 'text-muted'}`}
          />
        ) : null}
      </div>

      {node.description ? (
        <p
          className={`line-clamp-2 px-3 pt-1 text-[11px] ${customBg ? 'opacity-80' : 'text-muted'}`}
        >
          {node.description}
        </p>
      ) : null}

      {node.problem ? (
        <p className="px-3 pt-1 text-[11px] text-critical">{node.problem}</p>
      ) : null}
      {node.errored ? (
        <p className="px-3 pt-1 text-[11px] font-medium text-critical">
          {t('workflows.failedHere')}
        </p>
      ) : null}

      {/* Output handles are spread along the bottom and labelled underneath.
          An unlabelled fan of three lines out of an IF node is the fastest way
          to wire the false branch to the wrong place. */}
      <div className="relative mt-2 flex h-6 items-end justify-around px-2 pb-1">
        {handles.map((handle, index) => (
          <div key={handle.key} className="relative flex flex-1 justify-center">
            <span className={`text-[10px] ${customBg ? 'opacity-75' : 'text-muted'}`}>
              {definition
                ? t(`workflows.nodeTypes.${definition.key}.handles.${handle.key}`, {
                    defaultValue: handle.label,
                  })
                : handle.label}
            </span>
            <Handle
              id={handle.key}
              type="source"
              position={Position.Bottom}
              style={{ left: `${((index + 0.5) / handles.length) * 100}%` }}
              className={`!size-2 ${TONE_CLASS[handle.tone]}`}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * A sticky note. Decoration only: never executed, and nothing can connect
 * *into* it - but it can point a dashed annotation edge at a node, and it
 * resizes so a long remark does not have to squeeze into a card.
 */
export function NoteNode({ data, selected }: NodeProps) {
  const { t } = useTranslation()
  const node = data as WorkflowNodeData
  const customBg = node.color && contrastText(node.color) ? node.color : ''
  const fg = customBg ? contrastText(customBg) : ''

  return (
    <div
      className={`h-full min-h-[60px] w-full min-w-[160px] rounded-md border p-3 shadow-sm transition
        ${customBg ? '' : 'bg-warning-soft'}
        ${selected ? 'border-brand ring-2 ring-brand/35 shadow-lg' : customBg ? 'border-transparent' : 'border-warning/40'}`}
      style={customBg ? { background: customBg, color: fg } : undefined}
    >
      <NodeResizer
        isVisible={selected}
        minWidth={160}
        minHeight={60}
        maxWidth={640}
        maxHeight={480}
      />
      <div className="flex h-full items-start gap-2">
        <icons.StickyNote
          size={14}
          aria-hidden
          className={`mt-0.5 shrink-0 ${customBg ? 'opacity-80' : 'text-warning'}`}
        />
        <div className="min-w-0 flex-1 overflow-hidden">
          {node.label ? (
            <p className={`text-xs font-medium ${customBg ? '' : 'text-content'}`}>
              {node.label}
            </p>
          ) : null}
          <p
            className={`whitespace-pre-wrap text-[11px] leading-snug ${
              customBg ? 'opacity-85' : 'text-content/80'
            }`}
          >
            {node.description || (node.label ? '' : t('workflows.notePlaceholder'))}
          </p>
        </div>
      </div>
      {/* The annotation edge leaves from the right. Nothing can connect back
          into a note - the server refuses it. */}
      <Handle
        type="source"
        position={Position.Right}
        id="note"
        className="!size-2 !bg-warning"
        title={t('workflows.noteArrowHint')}
      />
    </div>
  )
}

/** Rotation per direction; the base glyph points right. */
const ARROW_ROTATION: Record<string, number> = {
  right: 0,
  'down-right': 45,
  down: 90,
  'down-left': 135,
  left: 180,
  'up-left': 225,
  up: 270,
  'up-right': 315,
}

/**
 * A big pointer arrow. Pure decoration - resize it, aim it with the
 * direction picker, colour it. It has no handles at all: an arrow exists to
 * *indicate*, and letting flow attach to scenery is how a drawing starts to
 * lie about what executes.
 */
export function ArrowNode({ data, selected }: NodeProps) {
  const node = data as WorkflowNodeData
  const direction = String(node.params?.direction ?? 'right')
  const rotation = ARROW_ROTATION[direction] ?? 0
  const color = node.color && contrastText(node.color) ? node.color : 'var(--warning)'

  return (
    <div
      className={`h-full min-h-[40px] w-full min-w-[60px] rounded transition ${
        selected ? 'ring-2 ring-brand/50' : ''
      }`}
    >
      <NodeResizer
        isVisible={selected}
        minWidth={60}
        minHeight={40}
        maxWidth={640}
        maxHeight={640}
      />
      <svg
        viewBox="0 0 100 60"
        preserveAspectRatio="none"
        className="h-full w-full"
        style={{ transform: `rotate(${rotation}deg)`, transformOrigin: 'center' }}
        aria-hidden
      >
        <path d="M0,22 H60 V6 L100,30 60,54 V38 H0 Z" fill={color} opacity={0.9} />
      </svg>
    </div>
  )
}
