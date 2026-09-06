/**
 * 量測值 SPC（WP-14）：統計頁「量測值」分頁——選具名輸出 → I-MR 或 X̄-R 管制圖（CL／UCL／LCL、規格 USL／LSL）、
 * Cp／Cpk、Nelson 判異法則標記；資料來自 GET /flows/{id}/spc（MeasurementLog）。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

import { Card, CardBody, CardHeader, EmptyState, ErrorState, LoadingState, SegmentedControl, Select, Tile } from '@/components/ui'
import { formatDateTime } from '@/lib/format'
import { useFlowSpc } from '@/lib/queries'
import type { SpcResult } from '@/lib/types'

const HOURS = ['24', '168', '720'] as const

const fmt = (v: number | null | undefined, nd = 3) => (v == null || !Number.isFinite(v) ? '—' : v.toFixed(nd))

function FlagDot(props: { cx?: number; cy?: number; payload?: { flagged?: boolean } }) {
  const { cx, cy, payload } = props
  if (cx == null || cy == null) return null
  return payload?.flagged ? <circle cx={cx} cy={cy} r={4} fill="var(--critical)" stroke="none" /> : <circle cx={cx} cy={cy} r={2} fill="var(--brand)" stroke="none" />
}

export function SpcPanel({ flowId }: { flowId: number }) {
  const { t } = useTranslation()
  const [output, setOutput] = useState('')
  const [chart, setChart] = useState<'imr' | 'xbar_r'>('imr')
  const [subgroup, setSubgroup] = useState(5)
  const [hours, setHours] = useState<(typeof HOURS)[number]>('24')
  const q = useFlowSpc(flowId, { output, chart, subgroup, hours: Number(hours) })
  const d: SpcResult | undefined = q.data
  const limits = d?.analysis.limits
  const cap = d?.analysis.capability
  const flagged = useMemo(() => new Set(d?.analysis.flagged ?? []), [d])
  const points = useMemo(() => {
    if (!d) return []
    if (chart === 'xbar_r' && limits?.xbar) {
      return limits.xbar.map((v, i) => ({ i: i + 1, value: v, flagged: flagged.has(i), ts: '' }))
    }
    return d.series.map((s, i) => ({ i: i + 1, value: s.value, flagged: flagged.has(i), ts: s.ts }))
  }, [d, chart, limits, flagged])
  const ruleEntries = Object.entries(d?.analysis.rules ?? {})

  return (
    <Card testId="spc-panel">
      <CardHeader
        title={t('spc.title')}
        description={d?.enabled === false ? t('spc.disabled') : t('spc.subtitle', { days: d?.retention_days ?? '' })}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Select value={d?.output ?? output} onChange={(e) => setOutput(e.target.value)} aria-label={t('spc.output')} data-testid="spc-output"
              options={(d?.outputs?.length ? d.outputs : ['']).map((n) => ({ value: n, label: n || t('spc.noOutputs') }))} />
            <SegmentedControl size="sm" value={chart} onChange={(v) => setChart(v as 'imr' | 'xbar_r')} options={[{ value: 'imr', label: t('spc.imr') }, { value: 'xbar_r', label: t('spc.xbarR') }]} />
            {chart === 'xbar_r' ? (
              <label className="flex items-center gap-1 text-xs text-muted">{t('spc.subgroup')}
                <input type="number" min={2} max={10} value={subgroup} onChange={(e) => setSubgroup(Math.max(2, Math.min(10, Number(e.target.value) || 2)))} className="input w-16" />
              </label>
            ) : null}
            <SegmentedControl size="sm" value={hours} onChange={(v) => setHours(v as (typeof HOURS)[number])} options={HOURS.map((h) => ({ value: h, label: t(`spc.hours.${h}`) }))} />
          </div>
        }
      />
      <CardBody>
        {q.isPending ? <LoadingState /> : q.isError ? <ErrorState error={q.error} onRetry={() => void q.refetch()} /> : !d || !d.series.length ? (
          <EmptyState title={t('spc.empty')} description={t('spc.emptyHint')} />
        ) : (
          <div className="space-y-4">
            <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <Tile label="n" value={d.analysis.summary.n} />
              <Tile label={t('spc.mean')} value={fmt(d.analysis.summary.mean)} />
              <Tile label="σ" value={fmt(limits?.sigma)} />
              <Tile label="Cp" value={fmt(cap?.cp, 2)} tone={cap?.cp != null ? (cap.cp >= 1.33 ? 'ok' : cap.cp >= 1 ? 'warning' : 'critical') : ''} />
              <Tile label="Cpk" value={fmt(cap?.cpk, 2)} tone={cap?.cpk != null ? (cap.cpk >= 1.33 ? 'ok' : cap.cpk >= 1 ? 'warning' : 'critical') : ''} />
              <Tile label={t('spc.outOfSpec')} value={cap?.out_of_spec ?? '—'} tone={cap?.out_of_spec ? 'critical' : ''} />
            </div>
            <div className="h-64" data-testid="spc-chart">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={points} margin={{ top: 8, right: 16, bottom: 4, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--line)" />
                  <XAxis dataKey="i" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} domain={['auto', 'auto']} width={64} />
                  <Tooltip formatter={(v: number) => fmt(v, 4)} labelFormatter={(_l, payload) => (payload?.[0]?.payload?.ts ? formatDateTime(payload[0].payload.ts) : '')} />
                  {limits?.cl != null ? <ReferenceLine y={limits.cl} stroke="var(--brand)" strokeDasharray="4 2" label={{ value: 'CL', fontSize: 10, position: 'right' }} /> : null}
                  {limits?.ucl != null ? <ReferenceLine y={limits.ucl} stroke="var(--warning)" label={{ value: 'UCL', fontSize: 10, position: 'right' }} /> : null}
                  {limits?.lcl != null ? <ReferenceLine y={limits.lcl} stroke="var(--warning)" label={{ value: 'LCL', fontSize: 10, position: 'right' }} /> : null}
                  {cap?.usl != null ? <ReferenceLine y={cap.usl} stroke="var(--critical)" strokeDasharray="2 2" label={{ value: 'USL', fontSize: 10, position: 'left' }} /> : null}
                  {cap?.lsl != null ? <ReferenceLine y={cap.lsl} stroke="var(--critical)" strokeDasharray="2 2" label={{ value: 'LSL', fontSize: 10, position: 'left' }} /> : null}
                  <Line type="monotone" dataKey="value" stroke="var(--brand)" strokeWidth={1.5} dot={<FlagDot />} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
            <div className="grid gap-3 text-xs text-muted sm:grid-cols-2">
              <div>
                <div className="font-medium text-fg">{t('spc.limits')}</div>
                <div className="tnum">CL {fmt(limits?.cl)} · UCL {fmt(limits?.ucl)} · LCL {fmt(limits?.lcl)}{chart === 'imr' && limits?.mr_ucl != null ? ` · MR UCL ${fmt(limits.mr_ucl)}` : ''}{chart === 'xbar_r' && limits?.r_ucl != null ? ` · R̄ ${fmt(limits.r_bar)} · R UCL ${fmt(limits.r_ucl)}` : ''}</div>
                <div>{d.spec.usl != null ? t('spc.specFrom', { usl: fmt(d.spec.usl), lsl: fmt(d.spec.lsl), unit: d.spec.unit ?? '' }) : t('spc.noSpec')}</div>
              </div>
              <div>
                <div className="font-medium text-fg">{t('spc.rulesTitle')}</div>
                {ruleEntries.length === 0 ? <div>{t('spc.inControl')}</div> : (
                  <ul className="list-disc pl-4" data-testid="spc-rules">
                    {ruleEntries.map(([k, idx]) => <li key={k}>{t(`spc.rules.${k}`)} — {t('spc.points', { count: idx.length })}</li>)}
                  </ul>
                )}
              </div>
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  )
}
