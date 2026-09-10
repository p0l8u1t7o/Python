/** 註冊式步驟的描述子快照，與專案模型共用版本紀錄。 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Button } from '@/components/ui'
import { api } from '@/lib/api'
import { useFlow, useFlows } from '@/lib/queries'
import type { DlModelVersion } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

export function RegistrationVersionsPanel() {
  const { t } = useTranslation()
  const flows = useFlows()
  const [flowId, setFlowId] = useState<number | null>(null)
  return <details className="mt-4 rounded border border-line p-3">
    <summary className="cursor-pointer font-medium">{t('dl.versions.registrations')}</summary>
    <div className="mt-3 space-y-3">
      <select className="rounded border border-line bg-surface p-2" aria-label={t('dl.versions.selectFlow')} value={flowId ?? ''} onChange={e => setFlowId(e.target.value ? Number(e.target.value) : null)}>
        <option value="">{t('dl.versions.selectFlow')}</option>
        {flows.data?.items.map(flow => <option key={flow.id} value={flow.id}>{flow.name}</option>)}
      </select>
      {flowId !== null ? <RegistrationSteps key={flowId} flowId={flowId} /> : null}
    </div>
  </details>
}

function RegistrationSteps({ flowId }: { flowId: number }) {
  const { t } = useTranslation()
  const flow = useFlow(flowId)
  const [selected, setSelected] = useState('')
  const nodes = flow.data?.graph.nodes.filter(n => ['register_detect', 'register_segment'].includes(n.type)) ?? []
  const nodeId = nodes.some(n => n.id === selected) ? selected : nodes[0]?.id ?? ''
  const base = `/vision/dl/registrations/${flowId}/${encodeURIComponent(nodeId)}/models`
  const auth = useAuth()
  const toast = useToast()
  const [busy, setBusy] = useState(false)
  const versions = useQuery({ queryKey: ['dl', 'registrations', flowId, nodeId], queryFn: () => api.get<{ items: DlModelVersion[] }>(base), enabled: !!nodeId })
  async function action(suffix = '') {
    setBusy(true)
    try {
      await api.post(base + suffix, { expected_updated_at: flow.data?.updated_at })
      await versions.refetch()
      await flow.refetch()
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  if (!nodes.length) return <p className="text-sm text-muted">{t('dl.versions.noRegistrations')}</p>
  return <div className="space-y-3">
    <div className="flex flex-wrap gap-2">
      <select className="rounded border border-line bg-surface p-2" aria-label={t('dl.versions.selectStep')} value={nodeId} onChange={e => setSelected(e.target.value)}>
        {nodes.map(node => <option key={node.id} value={node.id}>{node.label || node.id}</option>)}
      </select>
      {auth.can('dl') ? <Button disabled={busy} onClick={() => void action()}>{t('dl.versions.snapshot')}</Button> : null}
    </div>
    {versions.error ? <p role="alert">{versions.error.message}</p> : null}
    {versions.data?.items.map(v => <div className="flex flex-wrap items-center gap-2 text-sm" key={v.id}>
      <span>#{v.number} · {t(`dl.versions.${v.status}`)}</span>
      {auth.can('dl') ? <>
        <Button size="sm" disabled={busy || v.status === 'active'} onClick={() => void action(`/${v.number}/activate`)}>{t('dl.versions.activate')}</Button>
        <Button size="sm" disabled={busy || v.status !== 'active' || !v.parent} onClick={() => void action(`/${v.number}/rollback`)}>{t('dl.versions.rollback')}</Button>
        {auth.can('flows.edit') ? <Button size="sm" disabled={busy} onClick={() => void action(`/${v.number}/apply-to-flow`)}>{t('dl.versions.apply')}</Button> : null}
      </> : null}
    </div>)}
  </div>
}
