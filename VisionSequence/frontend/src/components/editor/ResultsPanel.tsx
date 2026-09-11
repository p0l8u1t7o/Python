/** 結果分頁（ResultsPanel）：最近執行、所選步驟的 outputs / message / 耗時 / logs、整個 run 的具名輸出、失敗時的醒目錯誤區塊。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { TriangleAlert } from 'lucide-react'

import { Button, DetailRow, Select, StatusBadge, Tile } from '@/components/ui'
import { calculateSpanTiming } from '@/lib/spanTiming'
import { isImageRef, type GraphEdge, type GraphNode, type NodeReport, type RunReport } from '@/lib/types'
import i18next from '@/i18n'
import { nodeMessage } from '@/lib/toolMessages'

/** run 裡第一個失敗的步驟（沒有就看 run.error）。 */
export function firstFailure(run: RunReport | null, order: string[]): { nodeId: string | null; message: string } | null {
  if (!run) return null
  const ids = [...order, ...Object.keys(run.nodes).filter((id) => !order.includes(id))]
  for (const id of ids) {
    const report = run.nodes[id]
    if (report?.status === 'error') return { nodeId: id, message: nodeMessage(report, i18next.language) || run.error || '' }
  }
  if (run.status === 'failed' && run.error) return { nodeId: null, message: run.error }
  return null
}

/** 結果分頁頂端的錯誤區塊：步驟名稱＋訊息＋「前往該步驟」。 */
export function RunErrorBlock({ run, order, payloads, onGoto }: { run: RunReport | null; order: string[]; payloads: Map<string, GraphNode>; onGoto: (nodeId: string) => void }) {
  const { t } = useTranslation()
  const failure = firstFailure(run, order)
  if (!failure) return null
  const node = failure.nodeId ? payloads.get(failure.nodeId) : undefined
  const name = failure.nodeId ? node?.label || failure.nodeId : t('editor.result.flow')
  return (
    <div className="m-3 rounded-lg border border-critical/40 bg-critical-soft p-3 text-xs" role="alert" data-testid="run-error">
      <p className="flex items-center gap-1.5 font-semibold text-critical">
        <TriangleAlert size={14} /> {t('editor.result.failedAt', { name })}
      </p>
      <p className="mt-1 whitespace-pre-wrap break-words text-content">{failure.message || t('errors.generic')}</p>
      {failure.nodeId ? (
        <Button size="xs" className="mt-2" onClick={() => onGoto(failure.nodeId as string)} data-testid="goto-failed-node">
          {t('editor.result.gotoNode')}
        </Button>
      ) : null}
    </div>
  )
}

/** run.warnings（例如「未完成現場教導」、Modbus 寫入降級）：結果分頁頂端的黃色提示。 */
export function RunWarnings({ run }: { run: RunReport | null }) {
  const { t } = useTranslation()
  if (!run?.warnings?.length) return null
  return (
    <div className="m-3 rounded-lg border border-warning/40 bg-warning-soft p-3 text-xs" role="status" data-testid="run-warnings">
      <p className="flex items-center gap-1.5 font-semibold text-warning"><TriangleAlert size={14} /> {t('editor.warnings')}</p>
      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-content">
        {run.warnings.map((w, i) => <li key={i}>{w}</li>)}
      </ul>
    </div>
  )
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (isImageRef(value)) return `image ${value.width}×${value.height}${value.ref ? '' : ' (gone)'}`
  if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(3)
  if (typeof value === 'string') return value
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (Array.isArray(value)) return `[${value.length}]`
  const text = JSON.stringify(value)
  return text.length > 80 ? `${text.slice(0, 77)}…` : text
}

export function outputsSummary(outputs: Record<string, unknown>): string {
  const entries = Object.entries(outputs)
  if (entries.length === 0) return '—'
  return entries
    .slice(0, 4)
    .map(([k, v]) => `${k}=${formatValue(v)}`)
    .join('  ')
}

export function NodeResult({ report, run }: { report: NodeReport | undefined; run: RunReport | null }) {
  const { t } = useTranslation()
  if (!report) {
    return (
      <div className="p-3">
        <p className="text-xs text-muted">{t('editor.result.noResult')}</p>
        {run ? <RunOutputs run={run} /> : null}
      </div>
    )
  }
  return (
    <div className="space-y-3 p-3 text-sm">
      <dl>
        <DetailRow label={t('editor.result.status')}><StatusBadge status={report.status} /></DetailRow>
        <DetailRow label={t('editor.result.duration')}><span className="tnum">{report.duration_ms.toFixed(1)} ms</span></DetailRow>
        {report.branch ? <DetailRow label={t('editor.result.branch')} mono>{report.branch}</DetailRow> : null}
        <DetailRow label={t('editor.result.overlays')}>{(report.overlays ?? []).length}</DetailRow>
      </dl>
      {report.message ? <p className={`rounded-lg px-3 py-2 text-xs ${report.status === 'error' ? 'bg-critical-soft text-critical' : report.status === 'ng' ? 'bg-warning-soft text-warning' : 'bg-surface-muted text-content'}`}>{nodeMessage(report, i18next.language)}</p> : null}
      <div>
        <p className="label">{t('editor.result.outputs')}</p>
        <table className="w-full text-xs">
          <tbody className="divide-y divide-line">
            {Object.entries(report.outputs ?? {}).map(([key, value]) => (
              <tr key={key}>
                <td className="py-1 pr-2 font-mono text-muted">{key}</td>
                <td className="py-1 text-right font-mono" title={typeof value === 'object' ? JSON.stringify(value) : undefined}>{formatValue(value)}</td>
              </tr>
            ))}
            {Object.keys(report.outputs ?? {}).length === 0 ? (
              <tr><td className="py-1 text-muted">—</td></tr>
            ) : null}
          </tbody>
        </table>
      </div>
      {report.logs?.length ? (
        <div>
          <p className="label">{t('editor.result.logs')}</p>
          <ul className="max-h-40 space-y-0.5 overflow-y-auto font-mono text-[11px]">
            {(report.logs ?? []).map((log, i) => (
              <li key={i} className={log.level === 'error' ? 'text-critical' : log.level === 'warning' ? 'text-warning' : 'text-muted'}>
                [{log.level}] {log.message}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {Object.keys(report.detail ?? {}).filter((k) => !k.startsWith('_')).length ? (
        <details className="text-xs">
          <summary className="cursor-pointer text-muted">detail</summary>
          <pre className="mt-1 max-h-48 overflow-auto rounded bg-surface-muted p-2 font-mono text-[10px]">{JSON.stringify(Object.fromEntries(Object.entries(report.detail ?? {}).filter(([k]) => !k.startsWith('_'))), null, 2)}</pre>
        </details>
      ) : null}
      {run ? <RunOutputs run={run} /> : null}
    </div>
  )
}

function nodeLabel(node: GraphNode | undefined, id: string): string {
  return node?.label || id
}

export function SpanTimingCard({ run, nodes, edges }: { run: RunReport | null; nodes: GraphNode[]; edges: GraphEdge[] }) {
  const { t } = useTranslation()
  const [source, setSource] = useState('')
  const [target, setTarget] = useState('')
  const options = useMemo(() => nodes.filter((node) => Boolean(run?.nodes[node.id])), [nodes, run])
  const byId = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes])
  const sourceId = options.some((node) => node.id === source) ? source : options[0]?.id ?? ''
  const targetId = options.some((node) => node.id === target) ? target : options[options.length - 1]?.id ?? ''
  const result = useMemo(() => {
    if (!run || !sourceId || !targetId) return null
    return calculateSpanTiming(run.nodes, edges, sourceId, targetId)
  }, [run, edges, sourceId, targetId])
  const maxNodeMs = Math.max(0, ...(result?.nodes.map((node) => node.durationMs) ?? []))

  return (
    <div className="border-y border-line p-3" data-testid="span-timing-card">
      <div className="mb-2 flex items-center justify-between gap-2">
        <p className="text-xs font-semibold text-muted">{t('editor.span.title')}</p>
        {result?.hasPath ? <span className="tnum text-[11px] text-subtle">{result.percent.toFixed(1)}%</span> : null}
      </div>
      {!run ? (
        <p className="text-xs text-muted">{t('editor.span.noRun')}</p>
      ) : options.length === 0 ? (
        <p className="text-xs text-muted">{t('editor.span.noNodes')}</p>
      ) : (
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-2">
            <Select value={sourceId} onChange={(event) => setSource(event.target.value)} aria-label={t('editor.span.source')} options={options.map((node) => ({ value: node.id, label: nodeLabel(node, node.id) }))} />
            <Select value={targetId} onChange={(event) => setTarget(event.target.value)} aria-label={t('editor.span.target')} options={options.map((node) => ({ value: node.id, label: nodeLabel(node, node.id) }))} />
          </div>
          {result && !result.hasPath ? (
            <p className="rounded bg-surface-muted px-2 py-1.5 text-xs text-muted">{t('editor.span.noPath')}</p>
          ) : result ? (
            <>
              <div className="grid grid-cols-3 gap-2">
                <Tile label={t('editor.span.total')} value={Math.round(result.totalMs)} unit="ms" />
                <Tile label={t('editor.span.nodes')} value={result.nodeCount} />
                <Tile label={t('editor.span.percent')} value={result.percent.toFixed(1)} unit="%" />
              </div>
              <div className="space-y-1.5">
                {result.nodes.map((node) => (
                  <div key={node.id}>
                    <div className="mb-0.5 flex items-center justify-between gap-2 text-[11px]">
                      <span className="truncate text-content" title={nodeLabel(byId.get(node.id), node.id)}>{nodeLabel(byId.get(node.id), node.id)}</span>
                      <span className="tnum shrink-0 text-muted">{node.durationMs.toFixed(1)} ms</span>
                    </div>
                    <div className="h-1.5 overflow-hidden rounded bg-line/60">
                      <div className="h-full bg-brand" style={{ width: `${maxNodeMs > 0 ? Math.max(4, (node.durationMs / maxNodeMs) * 100) : 0}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </div>
      )}
    </div>
  )
}

export function RunOutputs({ run }: { run: RunReport }) {
  const { t } = useTranslation()
  return (
    <div className="border-t border-line pt-3">
      <div className="mb-1 flex items-center justify-between">
        <p className="label !mb-0">{t('editor.result.runOutputs')}</p>
        <StatusBadge status={run.status} />
      </div>
      {run.error ? <p className="mb-1 text-xs text-critical">{run.error}</p> : null}
      <table className="w-full text-xs">
        <tbody className="divide-y divide-line">
          {Object.entries(run.outputs ?? {}).map(([key, value]) => (
            <tr key={key}>
              <td className="py-1 pr-2 font-mono text-muted">{key}</td>
              <td className="py-1 text-right font-mono">{formatValue(value)}</td>
            </tr>
          ))}
          {Object.keys(run.outputs ?? {}).length === 0 ? <tr><td className="py-1 text-muted">—</td></tr> : null}
        </tbody>
      </table>
    </div>
  )
}

/** 最近 8 次 run 的小表。 */
export function RecentRunsTable({ runs, selectedId, onSelect }: { runs: RunReport[]; selectedId: string | null; onSelect: (run: RunReport) => void }) {
  const { t } = useTranslation()
  if (runs.length === 0) return <p className="px-3 py-2 text-xs text-muted">{t('editor.result.noRuns')}</p>
  return (
    <table className="w-full text-xs">
      <thead className="text-[10px] uppercase text-subtle">
        <tr>
          <th className="px-2 py-1 text-left font-medium">{t('editor.result.time')}</th>
          <th className="px-2 py-1 text-left font-medium">{t('editor.result.status')}</th>
          <th className="px-2 py-1 text-right font-medium">ms</th>
          <th className="px-2 py-1 text-left font-medium">{t('editor.result.trigger')}</th>
          {runs.some((r) => r.recipe) ? <th className="px-2 py-1 text-left font-medium">{t('editor.recipe')}</th> : null}
          <th className="px-2 py-1 text-left font-medium">{t('editor.result.outputsSummary')}</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-line">
        {runs.map((run) => (
          <tr key={run.id} onClick={() => onSelect(run)} className={`cursor-pointer hover:bg-surface-muted/70 ${selectedId === run.id ? 'bg-brand-soft/40' : ''}`}>
            <td className="tnum px-2 py-1 whitespace-nowrap">{new Date(run.started_at * 1000).toLocaleTimeString()}</td>
            <td className="px-2 py-1"><StatusBadge status={run.status} /></td>
            <td className="tnum px-2 py-1 text-right">{Math.round(run.duration_ms)}</td>
            <td className="px-2 py-1 text-muted">{run.trigger}</td>
            {runs.some((r) => r.recipe) ? <td className="max-w-[90px] truncate px-2 py-1 text-muted" title={run.recipe}>{run.recipe || '—'}</td> : null}
            <td className="max-w-[240px] truncate px-2 py-1 font-mono text-[10px] text-muted" title={JSON.stringify(run.outputs)}>{run.error || outputsSummary(run.outputs)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
