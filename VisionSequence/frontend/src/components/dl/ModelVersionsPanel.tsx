/** 候選版本與保留集證據；啟用不會改寫流程，套用由使用者逐步選取。 */
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { Button, LoadingState } from '@/components/ui'
import { api, dlSampleUrl } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { useDlModelVersions } from '@/lib/queries'
import type { DlModelComparison, DlModelFailure, DlModelFlow, DlModelVersion } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

export function ModelVersionsPanel({ projectId }: { projectId: number }) {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const client = useQueryClient()
  const versions = useDlModelVersions(projectId)
  const [selected, setSelected] = useState<number | null>(null)
  const [other, setOther] = useState('')
  const [comparison, setComparison] = useState<DlModelComparison | null>(null)
  const [previousFlows, setPreviousFlows] = useState<DlModelFlow[]>([])
  const [busy, setBusy] = useState(false)
  const current = versions.data?.find(v => v.number === selected) ?? versions.data?.[0]
  const oldFlows = previousFlows.length ? previousFlows : versions.data?.filter(v => v.id !== current?.id).flatMap(v => v.flows) ?? []
  const base = `/vision/dl/projects/${projectId}/models`

  async function act(action: () => Promise<void>) {
    setBusy(true)
    try { await action() } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  async function transition(version: DlModelVersion, action: 'activate' | 'rollback') {
    const response = await api.post<{ version: DlModelVersion; flows_using_previous: DlModelFlow[] }>(`${base}/${version.number}/${action}`, {})
    setSelected(response.version.number)
    setPreviousFlows(response.flows_using_previous)
    await client.invalidateQueries({ queryKey: ['dl'] })
  }

  async function correct(failure: DlModelFailure, versionId: number) {
    const response = await api.post<{ holdout: boolean }>(`/vision/dl/projects/${projectId}/corrections`, { sample_id: failure.sample_id, model_version: versionId })
    toast.success(t(response.holdout ? 'dl.versions.holdoutCorrection' : 'dl.versions.correctionAdded'))
    await client.invalidateQueries({ queryKey: ['dl'] })
  }

  function failures(items: DlModelFailure[], versionId: number) {
    return <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">{items.map(item => <div key={item.sample_id} className="rounded border border-line p-2 text-xs">
      <img src={`${dlSampleUrl(item.sample_id, 160)}&model_version=${versionId}`} alt={t('dl.versions.sample')} className="h-24 w-full object-contain" />
      <p className="break-words">{t('dl.versions.truth')}: {JSON.stringify(item.truth)}</p>
      <p className="break-words">{t('dl.versions.prediction')}: {JSON.stringify(item.prediction)}</p>
      {auth.can('dl') ? <Button size="sm" disabled={busy} onClick={() => void act(() => correct(item, versionId))}>{t('dl.versions.correction')}</Button> : null}
    </div>)}</div>
  }

  if (versions.isLoading) return <LoadingState compact />
  if (versions.error) return <p role="alert">{versions.error.message}</p>
  return <div className="space-y-4" data-testid="dl-model-versions">
    <p className="text-sm text-muted">{t('dl.versions.hint')}</p>
    {!versions.data?.length ? <p>{t('dl.versions.empty')}</p> : <>
      <div className="overflow-x-auto"><table className="w-full text-left text-sm">
        <thead><tr>{['number', 'status', 'metrics', 'errors', 'created', 'parent'].map(key => <th className="p-2" key={key}>{t(`dl.versions.${key}`)}</th>)}</tr></thead>
        <tbody>{versions.data.map(version => <tr key={version.id} className={current?.id === version.id ? 'bg-brand-soft' : ''}>
          <td className="p-2"><button className="text-brand underline" onClick={() => { setSelected(version.number); setComparison(null); setOther(''); setPreviousFlows([]) }}>#{version.number}</button></td>
          <td className="p-2">{t(`dl.versions.${version.status}`)}</td>
          <td className="p-2">{version.metrics.holdout_count === 0 ? t('dl.versions.noHoldout') : (['accuracy', 'auroc', 'iou'] as const).filter(k => version.metrics[k] != null).map(k => `${t(`dl.versions.${k}`)} ${(version.metrics[k]! * 100).toFixed(1)}%`).join(' · ') || '—'}</td>
          <td className="p-2">{version.metrics.error_count ?? '—'}</td>
          <td className="whitespace-nowrap p-2">{formatDateTime(version.created_at)}</td>
          <td className="p-2">{version.parent ? `#${version.parent}` : '—'}</td>
        </tr>)}</tbody>
      </table></div>
      {current ? <>
        <div className="flex flex-wrap gap-2">
          {auth.can('dl') ? <>
            <Button disabled={busy || current.status === 'active'} onClick={() => void act(() => transition(current, 'activate'))}>{t('dl.versions.activate')}</Button>
            <Button disabled={busy || current.status !== 'active' || !current.parent} onClick={() => void act(() => transition(current, 'rollback'))}>{t('dl.versions.rollback')}</Button>
          </> : null}
          <select aria-label={t('dl.versions.compareWith')} value={other} onChange={event => { setOther(event.target.value); setComparison(null) }} className="rounded border border-line bg-surface p-2">
            <option value="">{t('dl.versions.compareWith')}</option>
            {versions.data.filter(v => v.id !== current.id).map(v => <option key={v.id} value={v.number}>#{v.number}</option>)}
          </select>
          <Button disabled={!other || busy} onClick={() => void act(async () => { setComparison(await api.get<DlModelComparison>(`${base}/compare?a=${other}&b=${current.number}`)) })}>{t('dl.versions.compare')}</Button>
        </div>
        {comparison ? <div className="space-y-3">
          {comparison.truncated ? <p role="status">{t('dl.versions.truncated')}</p> : null}
          <h3>{t('dl.versions.fixed', { count: comparison.fixed.length })}</h3>{failures(comparison.fixed, comparison.a.id)}
          <h3>{t('dl.versions.new', { count: comparison.new.length })}</h3>{failures(comparison.new, comparison.b.id)}
        </div> : <><h3>{t('dl.versions.failures')}</h3>{failures(current.failures, current.id)}</>}
        <h3>{t('dl.versions.flows')}</h3>
        {current.flows.length ? current.flows.map(flow => <p key={`${flow.flow_id}:${flow.node_id}`}><Link className="text-brand" to={`/flows/${flow.flow_id}?focus=${encodeURIComponent(flow.node_id)}`}>{flow.name} / {flow.node_id}</Link></p>) : <p className="text-sm text-muted">{t('dl.versions.noFlows')}</p>}
        {oldFlows.length ? <><h3>{t('dl.versions.previousFlows')}</h3>{oldFlows.map(flow => <div key={`${flow.flow_id}:${flow.node_id}`} className="flex flex-wrap items-center gap-2">
          <span>{flow.name} / {flow.node_id}</span>
          {auth.can('dl') && auth.can('flows.edit') ? <Button disabled={busy} onClick={() => void act(async () => {
            await api.post(`${base}/${current.number}/apply-to-flow`, { flow_id: flow.flow_id, node_id: flow.node_id, expected_updated_at: flow.updated_at })
            setPreviousFlows(list => list.filter(x => x !== flow))
            await client.invalidateQueries({ queryKey: ['dl'] })
            await client.invalidateQueries({ queryKey: ['flows'] })
            toast.success(t('dl.versions.applied'))
          })}>{t('dl.versions.apply')}</Button> : null}
        </div>)}</> : null}
      </> : null}
    </>}
  </div>
}
