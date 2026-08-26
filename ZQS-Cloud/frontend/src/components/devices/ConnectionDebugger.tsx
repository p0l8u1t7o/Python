import { useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bug, ChevronDown, ChevronRight, Eraser, RefreshCw } from 'lucide-react'

import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import { errorMessage } from '@/lib/errors'
import { formatTime } from '@/lib/format'
import {
  useIngressDebugMutations,
  useIngressDebugStatus,
  useIngressDiagnosis,
  useIngressTraces,
} from '@/lib/queries'
import type { EdgeNode, IngressTrace } from '@/lib/types'
import { Badge, Button, Card, CardBody, CardHeader, Checkbox, Select, TextInput } from '@/components/ui'

/**
 * Connection debugger for device vendors.
 *
 * Flip the switch and every stage of the platform - broker, ingestor,
 * worker, host - writes what it decided about each packet from the chosen
 * gateway. The diagnosis on top walks the protocol steps and says where the
 * device stopped; the timeline below is the evidence. Off by default, expires
 * on its own, and costs nothing while off.
 */
const OUTCOME_TONE: Record<string, 'ok' | 'critical' | 'warning' | 'neutral' | 'info'> = {
  ok: 'ok',
  rejected: 'critical',
  dropped: 'critical',
  warning: 'warning',
  info: 'info',
}

export function ConnectionDebugger({
  nodes,
  initialNode,
  embedded = false,
}: {
  nodes: EdgeNode[]
  initialNode?: string
  /** Rendered inside another card: no header of its own, status badge inline. */
  embedded?: boolean
}) {
  const { t } = useTranslation()
  const { can } = useAuth()
  const toast = useToast()
  const status = useIngressDebugStatus()
  const { enable, disable, clear } = useIngressDebugMutations()
  const [node, setNode] = useState(initialNode ?? '')
  const [minutes, setMinutes] = useState(30)
  const [capture, setCapture] = useState(true)
  const [onlyProblems, setOnlyProblems] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)
  const enabled = status.data?.enabled ?? false

  useEffect(() => {
    if (!node && initialNode) setNode(initialNode)
  }, [initialNode, node])

  const traces = useIngressTraces({ node, enabled })
  const diagnosis = useIngressDiagnosis(node, enabled)
  const rows = useMemo(() => {
    const list = traces.data ?? []
    return onlyProblems ? list.filter((r) => r.outcome !== 'ok' && r.outcome !== 'info') : list
  }, [traces.data, onlyProblems])
  // Follow the tail only while rows are being appended. Scrolling on mount
  // would yank the whole page down to this card the moment it opens.
  const bottom = useRef<HTMLDivElement>(null)
  const previousCount = useRef(0)
  useEffect(() => {
    if (rows.length > previousCount.current && previousCount.current > 0) {
      bottom.current?.scrollIntoView({ block: 'nearest' })
    }
    previousCount.current = rows.length
  }, [rows.length])

  async function toggle() {
    try {
      if (enabled) await disable.mutateAsync()
      else await enable.mutateAsync({ minutes, node_filter: node, capture_payload: capture })
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const stateBadge = enabled ? (
    <Badge tone="ok">
      <span className="hud-live" />
      {t('gateways.debug.on', { until: status.data?.enabled_until ? formatTime(status.data.enabled_until) : '' })}
    </Badge>
  ) : (
    <Badge tone="neutral">{t('gateways.debug.off')}</Badge>
  )

  const body = (
       <div data-testid="connection-debugger" className="space-y-4">
        {embedded ? (
          <div className="flex items-start justify-between gap-3">
            <p className="text-xs text-muted">{t('gateways.debug.subtitle')}</p>
            {stateBadge}
          </div>
        ) : null}
        <div className="grid gap-3 sm:grid-cols-[1fr_auto_auto_auto] sm:items-end">
          <Select
            label={t('gateways.debug.node')}
            value={node}
            onChange={(event) => setNode(event.target.value)}
            placeholder={t('gateways.debug.allNodes')}
            options={nodes.map((item) => ({ value: item.node_id, label: `${item.node_id}${item.name && item.name !== item.node_id ? ` · ${item.name}` : ''}` }))}
            disabled={enabled}
          />
          <TextInput
            label={t('gateways.debug.minutes')}
            type="number"
            min={1}
            max={240}
            value={minutes}
            onChange={(event) => setMinutes(Number(event.target.value))}
            disabled={enabled}
            className="w-24"
          />
          <Checkbox label={t('gateways.debug.capture')} checked={capture} onChange={setCapture} disabled={enabled} />
          {can('device:write') ? (
            <Button
              variant={enabled ? 'secondary' : 'primary'}
              loading={enable.isPending || disable.isPending}
              onClick={() => void toggle()}
              data-testid="debug-toggle"
            >
              {enabled ? t('gateways.debug.stop') : t('gateways.debug.start')}
            </Button>
          ) : null}
        </div>

        {enabled && node ? (
          <div className="rounded-lg border border-line p-3" data-testid="debug-diagnosis">
            {diagnosis.data ? (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={diagnosis.data.verdict_level === 'ok' ? 'ok' : diagnosis.data.verdict_level === 'warning' ? 'warning' : diagnosis.data.verdict_level === 'error' ? 'critical' : 'neutral'}>
                    {diagnosis.data.verdict}
                  </Badge>
                  <span className="text-xs text-muted">
                    {t('gateways.debug.nodeState', {
                      status: diagnosis.data.status || '—',
                      group: diagnosis.data.group_id_expected,
                      seen: diagnosis.data.last_seen_at ? formatTime(diagnosis.data.last_seen_at) : '—',
                    })}
                  </span>
                </div>
                {diagnosis.data.findings.length > 0 ? (
                  <ul className="mt-2 space-y-1 text-sm">
                    {diagnosis.data.findings.map((f, index) => (
                      <li key={index} className="flex items-start gap-2">
                        <span className={`mt-1.5 size-2 shrink-0 rounded-full ${f.level === 'error' ? 'bg-critical' : f.level === 'warning' ? 'bg-warning' : 'bg-info'}`} aria-hidden />
                        <span>
                          {f.text}
                          {f.ref ? (
                            <span className="ml-1 text-xs text-muted">
                              （{t('gateways.debug.docs')} docs/{f.ref.replace(/#.*$/, '')}
                              {f.ref.includes('#') ? ` ${decodeURIComponent(f.ref.split('#')[1]).replace(/-/g, ' ')}` : ''}）
                            </span>
                          ) : null}
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : null}
                {Object.keys(diagnosis.data.last_by_kind).length > 0 ? (
                  <p className="mt-2 text-xs text-muted">
                    {t('gateways.debug.lastByKind')}{' '}
                    {Object.entries(diagnosis.data.last_by_kind).map(([kind, ts]) => `${kind} ${formatTime(ts)}`).join(' · ')}
                  </p>
                ) : null}
              </>
            ) : (
              <p className="text-sm text-muted">{t('common.loading')}…</p>
            )}
          </div>
        ) : null}

        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-3 text-xs text-muted">
            <span>{t('gateways.debug.count', { count: rows.length })}</span>
            <Checkbox label={t('gateways.debug.onlyProblems')} checked={onlyProblems} onChange={setOnlyProblems} />
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" onClick={() => void traces.refetch()} icon={<RefreshCw className="size-3.5" />}>
              {t('common.refresh')}
            </Button>
            {can('device:write') ? (
              <Button
                size="sm"
                icon={<Eraser className="size-3.5" />}
                onClick={() => void clear.mutateAsync().catch((error) => toast.error(errorMessage(error)))}
              >
                {t('gateways.debug.clear')}
              </Button>
            ) : null}
          </div>
        </div>

        <div className="max-h-[420px] overflow-auto rounded-lg border border-line font-mono text-xs" data-testid="debug-timeline">
          {rows.length === 0 ? (
            <p className="p-4 text-sm text-muted">{enabled ? t('gateways.debug.waiting') : t('gateways.debug.hint')}</p>
          ) : (
            <table className="w-full">
              <tbody>
                {rows.map((row) => (
                  <TraceRow key={row.id} row={row} open={expanded === row.id} onToggle={() => setExpanded(expanded === row.id ? null : row.id)} />
                ))}
              </tbody>
            </table>
          )}
          <div ref={bottom} />
        </div>
       </div>
  )

  if (embedded) return body
  return (
    <Card data-testid="connection-debugger-card">
      <CardHeader
        title={
          <span className="flex items-center gap-2">
            <Bug className="size-4 text-brand" aria-hidden />
            {t('gateways.debug.title')}
          </span>
        }
        description={t('gateways.debug.subtitle')}
        actions={stateBadge}
      />
      <CardBody className="space-y-4">{body}</CardBody>
    </Card>
  )
}

function TraceRow({ row, open, onToggle }: { row: IngressTrace; open: boolean; onToggle: () => void }) {
  const { t } = useTranslation()
  const hasDetail = Object.keys(row.detail ?? {}).length > 0 || row.topic
  return (
    <>
      <tr className="cursor-pointer border-b border-line hover:bg-surface-muted" onClick={onToggle} data-outcome={row.outcome}>
        <td className="w-6 px-2 py-1 text-subtle">{hasDetail ? (open ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />) : null}</td>
        <td className="whitespace-nowrap px-2 py-1 text-muted">{formatTime(row.ts)}</td>
        <td className="px-2 py-1"><Badge tone="neutral">{t(`gateways.debug.stages.${row.stage}`, { defaultValue: row.stage })}</Badge></td>
        <td className="px-2 py-1"><Badge tone={OUTCOME_TONE[row.outcome] ?? 'neutral'}>{row.outcome}</Badge></td>
        <td className="whitespace-nowrap px-2 py-1">{row.kind}</td>
        <td className="whitespace-nowrap px-2 py-1 text-muted">{row.edge_node_id}{row.device_id ? `/${row.device_id}` : ''}</td>
        <td className="px-2 py-1 font-sans">{row.message || row.reason}</td>
      </tr>
      {open ? (
        <tr className="border-b border-line bg-surface-muted/50">
          <td colSpan={7} className="px-3 py-2">
            {row.topic ? <p className="text-muted">topic: {row.topic}{row.size ? ` · ${row.size} bytes` : ''}</p> : null}
            {row.reason ? <p className="text-muted">reason: {row.reason}</p> : null}
            {Object.entries(row.detail ?? {})
              .filter(([key]) => key !== 'hex')
              .map(([key, value]) => (
                <p key={key} className="text-muted">{key}: {typeof value === 'string' ? value : JSON.stringify(value)}</p>
              ))}
            {typeof row.detail?.hex === 'string' ? <pre className="mt-1 whitespace-pre-wrap break-all text-[11px]">{row.detail.hex}</pre> : null}
          </td>
        </tr>
      ) : null}
    </>
  )
}

export default ConnectionDebugger
