/** 資料洞察：命中率／混淆矩陣、未命中影像、出錯節點、判定門檻建議（可套用）、具名輸出分佈、歷次趨勢、與上一次差異。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Lightbulb, Play } from 'lucide-react'

import { Histogram, binValues, fmtNum } from '@/components/editor/Histogram'
import { Badge, Button, Card, CardBody, CardHeader, Select, Tile } from '@/components/ui'
import { batchImageUrl, fmtPct, type BatchInsights as Insights, type BatchRun, type BatchSet, type Suggestion } from '@/lib/batch'

const COLORS = { ok: 'var(--ok)', ng: 'var(--warning)', failed: 'var(--critical)', line: 'var(--brand)' }

export function BatchInsightsPanel({ insights, runs, set, run, onApply, onPreview }: {
  insights: Insights | undefined
  runs: BatchRun[]
  set: BatchSet
  run: BatchRun
  onApply: (suggestions: Suggestion[], andRun: boolean) => void
  onPreview: (index: number) => void
}) {
  const { t } = useTranslation()
  const [outKey, setOutKey] = useState('')
  const history = useMemo(() => [...runs].filter((r) => r.status === 'done').reverse().map((r) => ({
    label: r.label || `#${r.id}`, ok: r.summary.ok ?? 0, ng: r.summary.ng ?? 0, failed: r.summary.failed ?? 0,
    match: r.summary.match_rate === null || r.summary.match_rate === undefined ? null : Math.round(r.summary.match_rate * 100),
  })), [runs])
  const outputKeys = useMemo(() => (insights?.outputs ?? []).map((o) => o.key), [insights])
  const key = outKey || outputKeys[0] || ''
  const hist = useMemo(() => {
    const items = run.items ?? []
    const vals = (exp: string) => items.filter((it) => it.expected === exp).map((it) => Number(it.outputs?.[key])).filter((v) => Number.isFinite(v))
    const all = items.map((it) => Number(it.outputs?.[key])).filter((v) => Number.isFinite(v))
    if (!all.length) return null
    const range = { min: Math.min(...all), max: Math.max(...all) }
    const bin = (xs: number[]) => (xs.length ? binValues([range.min, range.max, ...xs], 24).counts.map((c, i, arr) => (i === 0 || i === arr.length - 1 ? Math.max(0, c - 1) : c)) : [])
    return { range, ok: bin(vals('ok')), ng: bin(vals('ng')), all: binValues(all, 24).counts }
  }, [run.items, key])

  if (!insights || !insights.ready) return <p className="text-xs text-muted" data-testid="batch-insights-empty">{t('batchPage.insights.notReady')}</p>
  const c = insights.confusion
  const sug = insights.suggestions ?? []
  return (
    <div className="space-y-3" data-testid="batch-insights">
      {!insights.labeled ? <p className="rounded bg-warning-soft px-2 py-1 text-xs text-warning">{t('batchPage.insights.noLabels')}</p> : null}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
        <Tile label={t('batchPage.kpi.match')} value={insights.labeled ? `${insights.match}/${insights.labeled}` : '—'} unit={insights.labeled ? fmtPct(insights.match_rate) : undefined} tone={insights.labeled && insights.match === insights.labeled ? 'text-ok' : ''} />
        <Tile label={t('batchPage.insights.tp')} value={c.tp} tone="text-ok" />
        <Tile label={t('batchPage.insights.fn')} value={c.fn} tone={c.fn ? 'text-critical' : ''} />
        <Tile label={t('batchPage.insights.fp')} value={c.fp} tone={c.fp ? 'text-critical' : ''} />
        <Tile label={t('batchPage.insights.tn')} value={c.tn} tone="text-ok" />
      </div>

      <Card>
        <CardHeader title={<span className="flex items-center gap-1.5"><Lightbulb size={14} className="text-brand" />{t('batchPage.insights.judges')}</span>}
          actions={sug.length ? <span className="flex gap-1"><Button size="xs" onClick={() => onApply(sug, false)} data-testid="batch-apply-suggestions">{t('batchPage.insights.apply')}</Button><Button size="xs" variant="primary" icon={<Play size={12} />} onClick={() => onApply(sug, true)} data-testid="batch-apply-run">{t('batchPage.insights.applyAndRun')}</Button></span> : null} />
        <CardBody className="space-y-2 text-xs">
          {insights.judges.length === 0 ? <p className="text-muted">{t('batchPage.insights.noJudges')}</p> : null}
          {insights.judges.map((j) => (
            <div key={j.node} className="rounded-lg border border-line p-2" data-testid="batch-judge">
              <p className="flex flex-wrap items-center gap-1.5"><b>{j.label}</b><Badge>{j.type}</Badge><span className="text-muted">{t('batchPage.insights.valueFrom')} {j.value_from.label}.{j.value_from.port}</span>
                {j.separable === true ? <Badge tone="ok">{t('batchPage.insights.separable')}</Badge> : j.separable === false ? <Badge tone="warning">{t('batchPage.insights.overlap')}</Badge> : null}</p>
              <p className="mt-1 text-muted">
                {t('batchPage.insights.okRange')}：{j.values.expected_ok.n ? `${fmtNum(j.values.expected_ok.min ?? 0)}～${fmtNum(j.values.expected_ok.max ?? 0)}（${j.values.expected_ok.n}）` : '—'}
                {'　'}{t('batchPage.insights.ngRange')}：{j.values.expected_ng.n ? `${fmtNum(j.values.expected_ng.min ?? 0)}～${fmtNum(j.values.expected_ng.max ?? 0)}（${j.values.expected_ng.n}）` : '—'}
              </p>
              <p className="mt-1 font-mono text-[11px] text-muted">{Object.entries(j.current).map(([k, v]) => `${k}=${String(v)}`).join('  ')}</p>
              {j.suggestion ? (
                <p className="mt-1 text-brand">{t('batchPage.insights.suggestion')}：{Object.entries(j.suggestion).map(([k, v]) => `${k}=${v}`).join('、')}　{t('batchPage.insights.accNow')} {fmtPct(j.acc_now)} → {t('batchPage.insights.accSuggested')} {fmtPct(j.acc_suggested)}</p>
              ) : j.acc_now !== null ? <p className="mt-1 text-subtle">{t('batchPage.insights.noSuggestion')}（{t('batchPage.insights.accNow')} {fmtPct(j.acc_now)}）</p> : null}
            </div>
          ))}
        </CardBody>
      </Card>

      {insights.mismatches.length ? (
        <Card>
          <CardHeader title={`${t('batchPage.insights.mismatches')} (${insights.mismatches.length})`} />
          <CardBody className="flex flex-wrap gap-2">
            {insights.mismatches.map((m) => (
              <button key={m.index} type="button" className="w-24 text-left" onClick={() => onPreview(m.index)} title={m.reasons.join('；')}>
                <img src={batchImageUrl(set.id, m.index, 160)} alt={m.name} className="h-16 w-24 rounded bg-surface-muted object-contain" loading="lazy" />
                <p className="truncate text-[10px]"><span className="text-subtle">#{m.index + 1}</span> {m.name}</p>
                <p className="text-[10px] text-critical">{m.expected.toUpperCase()} → {m.status.toUpperCase()}</p>
              </button>
            ))}
          </CardBody>
        </Card>
      ) : null}

      {insights.error_nodes.length ? (
        <Card><CardHeader title={t('batchPage.insights.errorNodes')} /><CardBody className="text-xs">
          <ul className="list-disc pl-4 text-critical">{insights.error_nodes.map((e) => <li key={e.node}><b>{e.label}</b> ×{e.count}：<span className="text-muted">{e.message}</span></li>)}</ul>
        </CardBody></Card>
      ) : null}

      {insights.vs_parent ? (
        <Card><CardHeader title={t('batchPage.insights.vsParent')} /><CardBody className="space-y-1 text-xs">
          <p><Badge tone="ok">{t('batchPage.insights.improved', { count: insights.vs_parent.improved.length })}</Badge> <Badge tone={insights.vs_parent.regressed.length ? 'critical' : 'neutral'}>{t('batchPage.insights.regressed', { count: insights.vs_parent.regressed.length })}</Badge> <Badge>{t('batchPage.insights.changed', { count: insights.vs_parent.changed.length })}</Badge></p>
          {insights.vs_parent.param_diff?.rows.length ? <p className="font-mono text-[11px] text-muted">{t('batchPage.insights.paramDiff')}：{insights.vs_parent.param_diff.rows.map((r) => `${r.label}.${r.key} ${String(r.from)} → ${String(r.to)}`).join('；')}</p> : null}
        </CardBody></Card>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-2">
        <Card>
          <CardHeader title={t('batchPage.insights.trend')} />
          <CardBody className="h-56">
            {history.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={history} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                  <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--content-muted)' }} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 10, fill: 'var(--content-muted)' }} />
                  <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12 }} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Bar dataKey="ok" stackId="a" name="OK" fill={COLORS.ok} />
                  <Bar dataKey="ng" stackId="a" name="NG" fill={COLORS.ng} />
                  <Bar dataKey="failed" stackId="a" name={t('batchPage.kpi.failed')} fill={COLORS.failed} />
                </BarChart>
              </ResponsiveContainer>
            ) : <p className="text-xs text-muted">—</p>}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title={t('batchPage.insights.matchRate')} />
          <CardBody className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={history} margin={{ top: 8, right: 8, left: -16, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--content-muted)' }} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: 'var(--content-muted)' }} />
                <Tooltip contentStyle={{ background: 'var(--surface)', border: '1px solid var(--border)', fontSize: 12 }} />
                <Line type="monotone" dataKey="match" name="%" stroke={COLORS.line} dot strokeWidth={1.5} isAnimationActive={false} connectNulls />
              </LineChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>
      </div>

      {outputKeys.length ? (
        <Card>
          <CardHeader title={t('batchPage.insights.outputs')} actions={<Select className="!py-1 text-xs" value={key} onChange={(e) => setOutKey(e.target.value)} options={outputKeys.map((k) => ({ value: k, label: k }))} />} />
          <CardBody className="space-y-2">
            {hist ? (
              <div className="grid gap-3 sm:grid-cols-2">
                <Histogram bins={hist.ok.length ? hist.ok : hist.all} color={hist.ok.length ? COLORS.ok : COLORS.line} title={hist.ok.length ? t('batchPage.insights.okRange') : key} labels={[fmtNum(hist.range.min), fmtNum(hist.range.max)]} />
                {hist.ng.length ? <Histogram bins={hist.ng} color={COLORS.ng} title={t('batchPage.insights.ngRange')} labels={[fmtNum(hist.range.min), fmtNum(hist.range.max)]} /> : null}
              </div>
            ) : null}
            <table className="w-full text-xs"><tbody className="divide-y divide-line">
              {(insights.outputs.find((o) => o.key === key) ? [insights.outputs.find((o) => o.key === key)!] : []).flatMap((o) => [
                ['all', o.all], ['expected_ok', o.by_expected.ok], ['expected_ng', o.by_expected.ng], ['status_ok', o.by_status.ok], ['status_ng', o.by_status.ng],
              ] as const).map(([name, st]) => (
                <tr key={name}><td className="py-0.5 pr-2 text-muted">{t(`batchPage.insights.group.${name}`)}</td><td className="tnum py-0.5 font-mono text-[11px]">{st.n ? `n=${st.n}  min=${fmtNum(st.min ?? 0)}  max=${fmtNum(st.max ?? 0)}  mean=${fmtNum(st.mean ?? 0)}  σ=${fmtNum(st.std ?? 0)}` : '—'}</td></tr>
              ))}
            </tbody></table>
          </CardBody>
        </Card>
      ) : null}

      {insights.slowest.length ? (
        <p className="text-[11px] text-muted">{t('batchPage.insights.slowest')}：{insights.slowest.map((s) => `#${s.index + 1} ${Math.round(s.duration_ms)} ms`).join('、')}{insights.node_time.length ? `　${t('batchPage.insights.nodeTime')}：${insights.node_time.map((n) => `${n.label} ${Math.round(n.avg_ms)} ms`).join('、')}` : ''}</p>
      ) : null}
    </div>
  )
}
