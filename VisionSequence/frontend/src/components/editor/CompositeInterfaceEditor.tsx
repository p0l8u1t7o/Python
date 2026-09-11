/**
 * 複合工具的對外介面（PRODUCT-DIRECTION v2 §3-2／§3-3）：與埠介面編輯器同一套語意、另一個尺度——
 * 清單來源是內部所有節點的埠與參數，勾選＝成為對外埠／對外參數，排序＝對外由上至下，改名＝對外顯示名稱。
 * 對外參數還可以標成教導參數（站台參數卡與配方看得到）。
 */
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowDown, ArrowUp } from 'lucide-react'

import { interfaceCandidates, orderedParamSpecs, withParamOrder, withParamSpec, type ParamCandidate, type PortCandidate } from '@/lib/composite'
import { nodeInterface, withOutputAlias, withPortExposed, withPortOrder } from '@/lib/nodeInterface'
import { orderedPorts } from '@/lib/portLayout'
import { portColor } from '@/lib/ports'
import type { FlowGraph, NodeInterface, ToolPort, ToolTypeDef } from '@/lib/types'

interface Props {
  graph: FlowGraph
  defs: Map<string, ToolTypeDef>
  value: NodeInterface
  readOnly: boolean
  onChange: (next: NodeInterface) => void
}

export function CompositeInterfaceEditor({ graph, defs, value, readOnly, onChange }: Props) {
  const { t } = useTranslation()
  const candidates = useMemo(() => interfaceCandidates(graph, defs), [graph, defs])
  const node = useMemo(() => ({ interface: value }), [value])
  const iface = nodeInterface(node)
  const patch = (result: { interface?: NodeInterface }) => onChange(result.interface ?? {})

  const portSection = (side: 'in' | 'out', items: PortCandidate[]) => {
    // 依 interface 的 order 排（已勾選的在前面照順序，其餘照節點順序殿後）
    const asPorts: ToolPort[] = items.map((item) => ({ ...item.port, key: item.key, label: item.label }))
    const ordered = orderedPorts(asPorts, node, side)
    const specs = new Map((side === 'in' ? iface.inputs : iface.outputs).map((spec) => [spec.key, spec]))
    const exposedKeys = ordered.filter((port) => specs.get(port.key)?.exposed === true).map((port) => port.key)
    const byKey = new Map(items.map((item) => [item.key, item]))
    const move = (key: string, delta: number) => {
      const index = exposedKeys.indexOf(key)
      const target = index + delta
      if (index < 0 || target < 0 || target >= exposedKeys.length) return
      const next = [...exposedKeys]
      next.splice(index, 1)
      next.splice(target, 0, key)
      patch(withPortOrder(node, side, next))
    }
    return (
      <div data-testid={`composite-${side === 'in' ? 'inputs' : 'outputs'}`}>
        <p className="mb-1 text-xs font-semibold text-heading">{t(side === 'in' ? 'editor.inputs' : 'editor.outputs')}</p>
        {ordered.length === 0 ? <p className="text-[11px] text-subtle">{t('editor.ports.none')}</p> : null}
        <ul className="space-y-1">
          {ordered.map((port) => {
            const item = byKey.get(port.key)
            const spec = specs.get(port.key)
            const exposed = spec?.exposed === true
            const locked = side === 'in' && Boolean(item?.connectedInside)
            const position = exposedKeys.indexOf(port.key)
            return (
              <li key={port.key} className={`flex items-center gap-1.5 rounded-md border border-line bg-surface px-1.5 py-1 ${exposed ? '' : 'opacity-70'}`} data-testid={`composite-port-${side}-${port.key}`} data-exposed={exposed ? 'true' : 'false'}>
                <input
                  type="checkbox"
                  className="size-4 shrink-0 rounded border-line accent-[var(--brand)]"
                  checked={exposed}
                  disabled={readOnly || locked}
                  title={locked ? t('editor.composite.connectedInside') : t('editor.composite.expose')}
                  aria-label={`${t('editor.composite.expose')}: ${port.label}`}
                  onChange={(event) => patch(withPortExposed(node, side, port.key, event.target.checked ? true : undefined))}
                  data-testid={`composite-expose-${side}-${port.key}`}
                />
                <span className={`size-2 shrink-0 ${port.type === 'flow' ? 'rotate-45' : 'rounded-full'}`} style={{ background: port.type === 'flow' ? 'var(--port-flow)' : portColor(port.type) }} aria-hidden />
                <span className="min-w-0 flex-1 truncate text-xs" title={`${port.label} (${port.type})`}>
                  {port.label}
                  {port.required && side === 'in' ? <span className="text-critical">*</span> : null}
                </span>
                {exposed ? (
                  <input
                    type="text"
                    className="h-6 w-28 shrink-0 rounded border border-line bg-surface px-1.5 text-[11px]"
                    value={spec?.alias ?? ''}
                    placeholder={t('editor.composite.aliasPlaceholder')}
                    title={t('editor.composite.alias')}
                    aria-label={`${t('editor.composite.alias')}: ${port.label}`}
                    disabled={readOnly}
                    onChange={(event) => patch(side === 'out' ? withOutputAlias(node, port.key, event.target.value) : withInputAlias(node, port.key, event.target.value))}
                    data-testid={`composite-alias-${side}-${port.key}`}
                  />
                ) : null}
                {exposed ? (
                  <span className="flex shrink-0 items-center">
                    <button type="button" className="btn-icon !p-0.5" title={t('editor.ports.moveUp')} aria-label={`${t('editor.ports.moveUp')}: ${port.label}`} disabled={readOnly || position <= 0} onClick={() => move(port.key, -1)} data-testid={`composite-up-${side}-${port.key}`}>
                      <ArrowUp size={12} />
                    </button>
                    <button type="button" className="btn-icon !p-0.5" title={t('editor.ports.moveDown')} aria-label={`${t('editor.ports.moveDown')}: ${port.label}`} disabled={readOnly || position < 0 || position >= exposedKeys.length - 1} onClick={() => move(port.key, 1)} data-testid={`composite-down-${side}-${port.key}`}>
                      <ArrowDown size={12} />
                    </button>
                  </span>
                ) : null}
              </li>
            )
          })}
        </ul>
      </div>
    )
  }

  const paramSection = (items: ParamCandidate[]) => {
    const specs = orderedParamSpecs(value)
    const byKey = new Map(items.map((item) => [item.key, item]))
    const exposedKeys = specs.map((spec) => spec.key).filter((key) => byKey.has(key))
    const ordered = [...exposedKeys.map((key) => byKey.get(key) as ParamCandidate), ...items.filter((item) => !exposedKeys.includes(item.key))]
    const move = (key: string, delta: number) => {
      const index = exposedKeys.indexOf(key)
      const target = index + delta
      if (index < 0 || target < 0 || target >= exposedKeys.length) return
      const next = [...exposedKeys]
      next.splice(index, 1)
      next.splice(target, 0, key)
      onChange(withParamOrder(value, next))
    }
    return (
      <div data-testid="composite-params">
        <p className="mb-1 text-xs font-semibold text-heading">{t('editor.parameters')}</p>
        <p className="mb-1 text-[11px] text-muted">{t('editor.composite.paramsHint')}</p>
        {ordered.length === 0 ? <p className="text-[11px] text-subtle">{t('editor.ports.none')}</p> : null}
        <ul className="space-y-1">
          {ordered.map((item) => {
            const spec = specs.find((entry) => entry.key === item.key)
            const exposed = Boolean(spec)
            const position = exposedKeys.indexOf(item.key)
            return (
              <li key={item.key} className={`flex flex-wrap items-center gap-1.5 rounded-md border border-line bg-surface px-1.5 py-1 ${exposed ? '' : 'opacity-70'}`} data-testid={`composite-param-${item.key}`} data-exposed={exposed ? 'true' : 'false'}>
                <input
                  type="checkbox"
                  className="size-4 shrink-0 rounded border-line accent-[var(--brand)]"
                  checked={exposed}
                  disabled={readOnly}
                  title={t('editor.composite.exposeParam')}
                  aria-label={`${t('editor.composite.exposeParam')}: ${item.label}`}
                  onChange={(event) => onChange(withParamSpec(value, item.key, event.target.checked ? {} : null))}
                  data-testid={`composite-expose-param-${item.key}`}
                />
                <span className="min-w-0 flex-1 truncate text-xs" title={`${item.label} (${item.param.kind})`}>
                  {item.label}
                  <span className="ml-1 text-[10px] text-subtle">{item.param.kind}</span>
                </span>
                {exposed ? (
                  <>
                    <input
                      type="text"
                      className="h-6 w-28 shrink-0 rounded border border-line bg-surface px-1.5 text-[11px]"
                      value={spec?.alias ?? ''}
                      placeholder={t('editor.composite.aliasPlaceholder')}
                      title={t('editor.composite.alias')}
                      aria-label={`${t('editor.composite.alias')}: ${item.label}`}
                      disabled={readOnly}
                      onChange={(event) => onChange(withParamSpec(value, item.key, { alias: event.target.value }))}
                      data-testid={`composite-alias-param-${item.key}`}
                    />
                    <label className="flex shrink-0 items-center gap-1 text-[11px] text-muted" title={t('editor.composite.teachHint')}>
                      <input type="checkbox" className="size-3.5 rounded border-line accent-[var(--brand)]" checked={spec?.teach ?? item.param.teach ?? false} disabled={readOnly} onChange={(event) => onChange(withParamSpec(value, item.key, { teach: event.target.checked }))} data-testid={`composite-teach-${item.key}`} />
                      {t('editor.composite.teach')}
                    </label>
                    <span className="flex shrink-0 items-center">
                      <button type="button" className="btn-icon !p-0.5" title={t('editor.ports.moveUp')} aria-label={`${t('editor.ports.moveUp')}: ${item.label}`} disabled={readOnly || position <= 0} onClick={() => move(item.key, -1)} data-testid={`composite-up-param-${item.key}`}>
                        <ArrowUp size={12} />
                      </button>
                      <button type="button" className="btn-icon !p-0.5" title={t('editor.ports.moveDown')} aria-label={`${t('editor.ports.moveDown')}: ${item.label}`} disabled={readOnly || position < 0 || position >= exposedKeys.length - 1} onClick={() => move(item.key, 1)} data-testid={`composite-down-param-${item.key}`}>
                        <ArrowDown size={12} />
                      </button>
                    </span>
                  </>
                ) : null}
              </li>
            )
          })}
        </ul>
      </div>
    )
  }

  return (
    <div className="space-y-3" data-testid="composite-interface">
      <p className="text-[11px] leading-relaxed text-muted">{t('editor.composite.interfaceHint')}</p>
      {portSection('in', candidates.inputs)}
      {portSection('out', candidates.outputs)}
      {paramSection(candidates.params)}
    </div>
  )
}

/** 對外輸入埠的顯示名稱（輸出埠沿用 withOutputAlias；輸入埠的 alias 只是名稱，不發布任何東西）。 */
function withInputAlias(node: { interface?: NodeInterface }, key: string, alias: string): { interface?: NodeInterface } {
  const iface = nodeInterface(node)
  const inputs = iface.inputs.map((spec) => {
    if (spec.key !== key) return spec
    const { alias: _dropped, ...rest } = spec
    return alias.trim() ? { ...rest, alias } : rest
  })
  return { interface: { ...(node.interface ?? {}), inputs } }
}
