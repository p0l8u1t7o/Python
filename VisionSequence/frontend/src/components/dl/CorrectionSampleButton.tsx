/** 批次誤判回收：使用既有影像，不要求使用者重新下載上傳。 */
import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Button, Modal } from '@/components/ui'
import { api } from '@/lib/api'
import { useDlProjects } from '@/lib/queries'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

export function CorrectionSampleButton({ runId, index }: { runId: number; index: number }) {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const client = useQueryClient()
  const projects = useDlProjects()
  const [open, setOpen] = useState(false)
  const [projectId, setProjectId] = useState('')
  const [label, setLabel] = useState('')
  const [busy, setBusy] = useState(false)
  const project = projects.data?.find(p => String(p.id) === projectId)
  if (!auth.can('dl')) return null
  async function save() {
    setBusy(true)
    try {
      const result = await api.post<{ holdout: boolean }>(`/vision/dl/projects/${projectId}/corrections`, { batch_run_id: runId, index, label })
      await client.invalidateQueries({ queryKey: ['dl'] })
      toast.success(t(result.holdout ? 'dl.versions.holdoutCorrection' : 'dl.versions.correctionAdded'))
      setOpen(false)
    } catch (e) { toast.error(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  return <>
    <Button size="sm" onClick={() => setOpen(true)}>{t('dl.versions.correction')}</Button>
    <Modal open={open} onClose={() => setOpen(false)} title={t('dl.versions.correction')}>
      <div className="space-y-3">
        <label className="block">{t('dl.versions.project')}
          <select className="block w-full rounded border border-line bg-surface p-2" value={projectId} onChange={e => { setProjectId(e.target.value); setLabel('') }}>
            <option value="">{t('dl.versions.selectProject')}</option>
            {projects.data?.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
        </label>
        <label className="block">{t('dl.versions.truth')}
          <select className="block w-full rounded border border-line bg-surface p-2" value={label} onChange={e => setLabel(e.target.value)}>
            <option value="">{t('dl.versions.labelLater')}</option>
            {project?.classes.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <Button disabled={!project || busy} onClick={() => void save()}>{t('dl.versions.correction')}</Button>
      </div>
    </Modal>
  </>
}
