/**
 * 工具頁的埠編輯區（PRODUCT-DIRECTION v2 §2）：每個輸入／輸出埠要不要畫在畫布上、由上至下的順序、輸出的具名輸出名稱。
 * 這是唯一能改埠介面的地方；側欄只有「編輯埠…」入口。
 * - 已接線的埠鎖住不能隱藏（tooltip 說明先移除連線）
 * - 拖曳列（原生 HTML5 drag）或上下鍵重排；「依下游／上游位置自動排序」把連線交叉理掉
 * - 寫進 node.interface 的只有 exposed／order／alias；「還原預設」把顯示與順序清掉、名稱保留
 */
import { useEffect, useMemo, useState, type DragEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowDown, ArrowUp, GripVertical, RotateCcw, Shuffle } from 'lucide-react'

import { validatePublishName } from '@/lib/graphValidation'
import { outputAliases, withOutputAlias, withPortExposed, withPortLayoutReset, withPortOrder } from '@/lib/nodeInterface'
import { portColor } from '@/lib/ports'
import { autoOrderKeys, connectedHandles, portLayout, type PortSide, type PortView } from '@/lib/portLayout'
import type { GraphEdge, GraphNode, ToolTypeDef } from '@/lib/types'

interface Props {
  node: GraphNode
  /** 已含參數訂閱埠與動態分支埠的定義（graphMapping.effectiveDefinition） */
  definition: ToolTypeDef | undefined
  edges: GraphEdge[]
  nodes: GraphNode[]
  readOnly: boolean
  onChange: (patch: Partial<GraphNode>) => void
}

export function PortInterfaceEditor({ node, definition, edges, nodes, readOnly, onChange }: Props) {
  const { t } = useTranslation()
  const layoutIn = useMemo(() => portLayout(definition, node, 'in', connectedHandles(node.id, edges, 'in')), [definition, node, edges])
  const layoutOut = useMemo(() => portLayout(definition, node, 'out', connectedHandles(node.id, edges, 'out')), [definition, node, edges])
  if (!definition) return null
  return (
    <div className="space-y-3" data-testid="port-editor">
      <p className="text-[11px] leading-relaxed text-muted">{t('editor.ports.hint')}</p>
      <PortSideList side="in" views={layoutIn.all} node={node} definition={definition} edges={edges} nodes={nodes} readOnly={readOnly} onChange={onChange} />
      <PortSideList side="out" views={layoutOut.all} node={node} definition={definition} edges={edges} nodes={nodes} readOnly={readOnly} onChange={onChange} />
    </div>
  )
}

function PortSideList({ side, views, node, definition, edges, nodes, readOnly, onChange }: Props & { side: PortSide; views: PortView[]; definition: ToolTypeDef }) {
  const { t } = useTranslation()
  const [dragging, setDragging] = useState<string | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const keys = views.map((view) => view.port.key)
  const hasLinks = views.some((view) => view.connected)
  const customised = views.some((view) => view.customised)
  const hiddenMissing = views.filter((view) => !view.visible && view.missing)

  const move = (from: number, to: number) => {
    if (from === to || to < 0 || to >= keys.length) return
    const next = [...keys]
    const [key] = next.splice(from, 1)
    next.splice(to, 0, key)
    onChange(withPortOrder(node, side, next))
  }
  const onDrop = (event: DragEvent, targetKey: string) => {
    event.preventDefault()
    const from = keys.indexOf(dragging ?? event.dataTransfer.getData('text/plain'))
    const to = keys.indexOf(targetKey)
    setDragging(null)
    setOver(null)
    if (from >= 0 && to >= 0) move(from, to)
  }

  return (
    <div data-testid={`port-list-${side}`}>
      <div className="mb-1 flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-heading">{t(side === 'in' ? 'editor.inputs' : 'editor.outputs')}</p>
        <div className="flex items-center gap-1">
          <button type="button" className="btn-icon !p-1" title={t(side === 'in' ? 'editor.ports.autoSortInputs' : 'editor.ports.autoSortOutputs')} aria-label={t(side === 'in' ? 'editor.ports.autoSortInputs' : 'editor.ports.autoSortOutputs')} disabled={readOnly || !hasLinks} onClick={() => onChange(withPortOrder(node, side, autoOrderKeys(definition, node, side, edges, nodes)))} data-testid={`port-autosort-${side}`}>
            <Shuffle size={13} />
          </button>
          <button type="button" className="btn-icon !p-1" title={t('editor.ports.reset')} aria-label={t('editor.ports.reset')} disabled={readOnly || !customised} onClick={() => onChange(withPortLayoutReset(node, side))} data-testid={`port-reset-${side}`}>
            <RotateCcw size={13} />
          </button>
        </div>
      </div>
      {views.length === 0 ? <p className="text-[11px] text-subtle">{t('editor.ports.none')}</p> : null}
      <ul className="space-y-1">
        {views.map((view, index) => (
          <PortRowEditor
            key={view.port.key}
            side={side}
            view={view}
            node={node}
            index={index}
            count={views.length}
            readOnly={readOnly}
            dragOver={over === view.port.key && dragging !== view.port.key}
            onChange={onChange}
            onMove={move}
            onDragStart={(event) => {
              event.dataTransfer.effectAllowed = 'move'
              event.dataTransfer.setData('text/plain', view.port.key)
              setDragging(view.port.key)
            }}
            onDragOver={(event) => {
              event.preventDefault()
              if (over !== view.port.key) setOver(view.port.key)
            }}
            onDrop={(event) => onDrop(event, view.port.key)}
            onDragEnd={() => {
              setDragging(null)
              setOver(null)
            }}
          />
        ))}
      </ul>
      {hiddenMissing.length ? (
        <p className="mt-1.5 rounded-lg bg-critical-soft px-2.5 py-1.5 text-[11px] text-critical" data-testid="port-hidden-required">
          {t('editor.ports.hiddenRequired', { count: hiddenMissing.length, labels: hiddenMissing.map((view) => view.port.label).join(', ') })}
        </p>
      ) : null}
    </div>
  )
}

function PortRowEditor({ side, view, node, index, count, readOnly, dragOver, onChange, onMove, onDragStart, onDragOver, onDrop, onDragEnd }: {
  side: PortSide
  view: PortView
  node: GraphNode
  index: number
  count: number
  readOnly: boolean
  dragOver: boolean
  onChange: (patch: Partial<GraphNode>) => void
  onMove: (from: number, to: number) => void
  onDragStart: (event: DragEvent) => void
  onDragOver: (event: DragEvent) => void
  onDrop: (event: DragEvent) => void
  onDragEnd: () => void
}) {
  const { t } = useTranslation()
  const { port } = view
  const key = port.key
  const isFlow = port.type === 'flow'
  const canAlias = side === 'out' && !isFlow && port.implicit !== true
  const aliases = useMemo(() => outputAliases(node), [node])
  const saved = aliases[key] ?? ''
  const [alias, setAlias] = useState(saved)
  useEffect(() => setAlias(saved), [saved, node.id])
  const aliasInvalid = !validatePublishName(alias)
  const lockTitle = view.connected ? t('editor.ports.connectedLocked') : undefined

  return (
    <li
      className={`flex items-center gap-1.5 rounded-md border px-1.5 py-1 ${dragOver ? 'border-brand bg-brand-soft/40' : 'border-line bg-surface'} ${view.visible ? '' : 'opacity-70'}`}
      draggable={!readOnly}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDrop={onDrop}
      onDragEnd={onDragEnd}
      data-testid={`port-row-${side}-${key}`}
      data-visible={view.visible ? 'true' : 'false'}
      data-reason={view.reason}
    >
      <span className={`shrink-0 text-subtle ${readOnly ? 'opacity-40' : 'cursor-grab'}`} title={t('editor.ports.drag')} aria-hidden>
        <GripVertical size={13} />
      </span>
      <input
        type="checkbox"
        className="size-4 shrink-0 rounded border-line accent-[var(--brand)]"
        checked={view.visible}
        disabled={readOnly || view.connected}
        title={lockTitle ?? t('editor.ports.visible')}
        aria-label={`${t('editor.ports.visible')}: ${port.label}`}
        onChange={(event) => onChange(withPortExposed(node, side, key, event.target.checked))}
        data-testid={`port-visible-${side}-${key}`}
      />
      <span className={`size-2 shrink-0 ${isFlow ? 'rotate-45' : 'rounded-full'}`} style={{ background: isFlow ? 'var(--port-flow)' : portColor(port.type) }} aria-hidden />
      <span className="min-w-0 flex-1 truncate text-xs" title={`${port.label} (${port.type})`}>
        {port.label}
        {port.required && side === 'in' ? <span className="text-critical">*</span> : null}
        <span className="ml-1 text-[10px] text-subtle">{t(`editor.ports.reason.${view.reason}`)}</span>
      </span>
      {canAlias ? (
        <input
          type="text"
          className={`h-6 w-28 shrink-0 rounded border px-1.5 font-mono text-[11px] ${aliasInvalid ? 'border-critical' : 'border-line'} bg-surface`}
          value={alias}
          placeholder={t('editor.publishedOutputs.placeholder')}
          title={aliasInvalid ? t('editor.publishedOutputs.invalidName') : t('editor.ports.alias')}
          aria-label={`${t('editor.ports.alias')}: ${port.label}`}
          aria-invalid={aliasInvalid || undefined}
          disabled={readOnly}
          onChange={(event) => {
            const value = event.target.value
            setAlias(value)
            if (validatePublishName(value)) onChange(withOutputAlias(node, key, value))
          }}
          data-testid={`port-alias-${key}`}
        />
      ) : null}
      <span className="flex shrink-0 items-center">
        <button type="button" className="btn-icon !p-0.5" title={t('editor.ports.moveUp')} aria-label={`${t('editor.ports.moveUp')}: ${port.label}`} disabled={readOnly || index === 0} onClick={() => onMove(index, index - 1)} data-testid={`port-up-${side}-${key}`}>
          <ArrowUp size={12} />
        </button>
        <button type="button" className="btn-icon !p-0.5" title={t('editor.ports.moveDown')} aria-label={`${t('editor.ports.moveDown')}: ${port.label}`} disabled={readOnly || index >= count - 1} onClick={() => onMove(index, index + 1)} data-testid={`port-down-${side}-${key}`}>
          <ArrowDown size={12} />
        </button>
      </span>
    </li>
  )
}

/** 側欄用的一行摘要：顯示幾個埠、發布了哪些名稱。 */
export function portSummary(node: GraphNode, definition: ToolTypeDef | undefined, edges: GraphEdge[]): { shown: number; total: number; published: string[] } {
  const layoutIn = portLayout(definition, node, 'in', connectedHandles(node.id, edges, 'in'))
  const layoutOut = portLayout(definition, node, 'out', connectedHandles(node.id, edges, 'out'))
  const published = layoutOut.all.map((view) => outputAliases(node)[view.port.key]).filter((name): name is string => Boolean(name))
  return { shown: layoutIn.visible.length + layoutOut.visible.length, total: layoutIn.all.length + layoutOut.all.length, published }
}
