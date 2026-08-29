/**
 * 統計（StatsPage）`/flows/:id/stats`：期間（1h／8h／24h／7d）、KPI、每小時 OK/NG/失敗堆疊長條、
 * 耗時折線（runs 歷史）、執行歷史表（狀態篩選、分頁）。資料來自 GET /flows/{id}/stats 與 GET /flows/{id}/runs。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, BarChart3 } from 'lucide-react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { outputsSummary } from '@/components/editor/ResultsPanel'
import { Page } from '@/components/layout/AppShell'
import { Button, Card, CardBody, CardHeader, EmptyRow, ErrorState, LoadingState, PageHeader, SegmentedControl, Select, StatusBadge, TBody, THead, Table, Td, Th, Tr, Tile } from '@/components/ui'
import { useFlow, useFlowStats, useRunHistory } from '@/lib/queries'
import type { FlowStats } from '@/lib/types'

const PERIODS = ['1', '8', '24', '168'] as const
type Period = (typeof PERIODS)[number]
const PAGE_SIZE = 20

const COLORS = { ok: 'var(--ok)', ng: 'var(--warning)', failed: 'var(--critical)', line: 'var(--brand)' }

/** 最近 N 次 OK/NG 色塊條（總覽卡片與統計頁共用）。 */
export function TrendStrip({ statuses, className = '' }: { statuses: string[]; className?: string }) {
  if (!statuses.length) return null
  return (
    <div className={`flex h-2 gap-px overflow-hidden rounded ${className}`} aria-hidden>
      {statuses.map((s, i) => (
        <span key={i} className={`flex-1 ${s === 'ok' ? 'bg-ok' : s === 'ng' ? 'bg-warning' : 'bg-critical'}`} />
      ))}
    </div>
  )
}

function Kpi({ label, value, unit, tone = '' }: { label: string; value: string | number; unit?: string; tone?: string }) {
  return <Tile label={label} value={value} unit={unit} tone={tone} />
}

export function StatsPage() {
  const { t } = useTranslation()
  const { flowId } = useParams<{ flowId: string }>()
  const id = Number(flowId)
  const flow = useFlow(Number.isNaN(id) ? null : id)
  const [period, setPeriod] = useState<Period>('24')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const stats = useFlowStats(Number.isNaN(id) ? null : id, Number(period))
  const history = useRunHistory(Number.isNaN(id) ? null : id, { status, limit: PAGE_SIZE, offset })
  const series = useRunHistory(Number.isNaN(id) ? null : id, { limit: 100, offset: 0 })

  const durationData = useMemo(
    () => [...(series.data?.items ?? [])].reverse().map((r, i) => ({ i: i + 1, ms: Math.round(r.duration_ms * 10) / 10, status: r.status, time: new Date(r.started_at * 1000).toLocaleTimeString() })),
    [series.data],
  )
  const hourly = useMemo(() => (stats.data?.hourly ?? []).map((h) => ({ ...h, label: h.hour.slice(5) })), [stats.data])
  const trend = useMemo(() => [...(series.data?.items ?? [])].slice(0, 30).reverse().map((r) => r.status), [series.data])

  if (!flowId || Number.isNaN(id)) return null
  const d = stats.data
  const okCount = d?.by_status.ok ?? 0
  const yieldPct = d && d.total ? Math.round((okCount / d.total) * 1000) / 10 : null
  const live: FlowStats | undefined = d?.live
  const latest = series.data?.items[0]

  return (
    <Page wide>
      <PageHeader
        title={<span className="flex items-center gap-2"><BarChart3 size={20} className="text-brand" />{t('stats.title')}{flow.data ? <span className="text-muted">· {flow.data.name}</span> : null}</span>}
        description={<span>{t('stats.subtitle')}{latest?.station_id ? <span className="ml-2 text-xs">· {t('stats.station')} <code className="font-mono">{latest.station_id}</code></span> : null}{latest?.recipe ? <span className="ml-2 text-xs">· {t('stats.recipe')} <code className="font-mono">{latest.recipe}</code></span> : null}</span>}
        actions={
          <>
            <SegmentedControl size="sm" value={period} onChange={(v) => { setPeriod(v); setOffset(0) }} options={PERIODS.map((v) => ({ value: v, label: t(`stats.periods.${v}`) }))} />
            <Link to={`/flows/${id}`}><Button size="sm" icon={<ArrowLeft size={14} />}>{t('stats.backToEditor')}</Button></Link>
          </>
        }
      />
      {stats.isPending ? (
        <LoadingState />
      ) : stats.isError ? (
        <ErrorState error={stats.error} onRetry={() => void stats.refetch()} />
      ) : (
        <>
          <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6" data-testid="stats-kpi">
            <Kpi label={t('stats.total')} value={d?.total ?? 0} />
            <Kpi label={t('stats.yield')} value={yieldPct === null ? '—' : yieldPct} unit={yieldPct === null ? undefined : '%'} tone="text-ok" />
            <Kpi label={t('stats.ng')} value={d?.by_status.ng ?? 0} tone="text-warning" />
            <Kpi label={t('stats.failed')} value={(d?.total ?? 0) - okCount - (d?.by_status.ng ?? 0)} tone="text-critical" />
            <Kpi label={t('stats.avg')} value={Math.round(d?.avg_ms ?? 0)} unit="ms" />
            <Kpi label={t('stats.max')} value={Math.round(d?.max_ms ?? 0)} unit="ms" />
          </div>
          {live ? (
            <div className="mb-4 flex flex-wrap items-center gap-3 text-xs text-muted">
              <span>{t('stats.live')}：{live.runs} · OK {live.ok} · NG {live.ng} · {t('status.failed')} {live.failed} · {Math.round(live.avg_ms)} ms</span>
              {trend.length ? <span className="flex items-center gap-2">{t('stats.trend')} <TrendStrip statuses={trend} className="w-40" /></span> : null}
            </div>
          ) : null}
          <div className="mb-4 grid gap-4 xl:grid-cols-2">
            <Card>
              <CardHeader title={t('stats.hourly')} />
              <CardBody className="h-64">
                {hourly.length === 0 ? (
                  <p className="py-16 text-center text-sm text-muted">{t('stats.noData')}</p>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={hourly} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--content-muted)' }} />
                      <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: 'var(--content-muted)' }} />
                      <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12 }} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar dataKey="ok" stackId="a" name="OK" fill={COLORS.ok} />
                      <Bar dataKey="ng" stackId="a" name="NG" fill={COLORS.ng} />
                      <Bar dataKey="failed" stackId="a" name={t('status.failed')} fill={COLORS.failed} />
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </CardBody>
            </Card>
            <Card>
              <CardHeader title={t('stats.durations')} />
              <CardBody className="h-64">
                {durationData.length === 0 ? (
                  <p className="py-16 text-center text-sm text-muted">{t('stats.noData')}</p>
                ) : (
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={durationData} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                      <XAxis dataKey="i" tick={{ fontSize: 10, fill: 'var(--content-muted)' }} />
                      <YAxis tick={{ fontSize: 10, fill: 'var(--content-muted)' }} unit="ms" />
                      <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12 }} labelFormatter={(_l, payload) => (payload?.[0]?.payload as { time?: string } | undefined)?.time ?? ''} />
                      <Line type="monotone" dataKey="ms" stroke={COLORS.line} dot={false} strokeWidth={1.5} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </CardBody>
            </Card>
          </div>
          <Card className="overflow-hidden">
            <CardHeader
              title={t('stats.history')}
              actions={
                <Select className="!py-1 text-xs" value={status} onChange={(e) => { setStatus(e.target.value); setOffset(0) }} placeholder={t('stats.statusAll')} options={['ok', 'ng', 'failed', 'cancelled'].map((s) => ({ value: s, label: t(`status.${s}`) }))} data-testid="stats-status-filter" />
              }
            />
            {history.isPending ? (
              <LoadingState compact />
            ) : history.isError ? (
              <ErrorState error={history.error} onRetry={() => void history.refetch()} />
            ) : (
              <>
                <Table>
                  <THead>
                    <Th>{t('stats.cols.time')}</Th>
                    <Th>{t('stats.cols.status')}</Th>
                    <Th>{t('stats.cols.trigger')}</Th>
                    <Th>{t('stats.cols.recipe')}</Th>
                    <Th>{t('stats.cols.station')}</Th>
                    <Th align="right">{t('stats.cols.ms')}</Th>
                    <Th>{t('stats.cols.outputs')}</Th>
                    <Th>{t('stats.cols.error')}</Th>
                  </THead>
                  <TBody>
                    {history.data.items.length === 0 ? (
                      <EmptyRow colSpan={8} message={t('stats.noData')} />
                    ) : (
                      history.data.items.map((run) => (
                        <Tr key={run.id}>
                          <Td className="tnum whitespace-nowrap text-xs">{new Date(run.started_at * 1000).toLocaleString()}</Td>
                          <Td><StatusBadge status={run.status} /></Td>
                          <Td className="text-xs text-muted">{run.trigger}</Td>
                          <Td className="text-xs"><span data-testid="history-recipe">{run.recipe || '—'}</span></Td>
                          <Td className="font-mono text-xs text-muted">{run.station_id || '—'}</Td>
                          <Td align="right" className="tnum">{Math.round(run.duration_ms)}</Td>
                          <Td className="max-w-[320px] truncate font-mono text-[11px] text-muted"><span title={JSON.stringify(run.outputs)}>{outputsSummary(run.outputs)}</span></Td>
                          <Td className="max-w-[240px] truncate text-xs text-critical"><span title={run.error}>{run.error}</span></Td>
                        </Tr>
                      ))
                    )}
                  </TBody>
                </Table>
                <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-muted">
                  <span className="tnum">{t('common.showing', { from: history.data.total ? offset + 1 : 0, to: Math.min(offset + PAGE_SIZE, history.data.total), total: history.data.total })}</span>
                  <span className="flex gap-1">
                    <Button size="xs" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>{t('common.previous')}</Button>
                    <Button size="xs" disabled={offset + PAGE_SIZE >= history.data.total} onClick={() => setOffset(offset + PAGE_SIZE)}>{t('common.next')}</Button>
                  </span>
                </div>
              </>
            )}
          </Card>
        </>
      )}
    </Page>
  )
}
