/**
 * Archive affordances: a nudge when a flow throws rejects with archiving off, and the thumbnails
 * of an archived run. Runs whose pictures were kept can be opened long after the memory cache
 * dropped them — that is the whole point of the archive (see apps/vision/archive.py).
 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Archive, Image as ImageIcon } from 'lucide-react'

import { Badge, Button, Modal } from '@/components/ui'
import { imageUrl } from '@/lib/api'
import { useFlowMutations } from '@/lib/queries'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'
import type { Flow, RunReport } from '@/lib/types'

/** Shown on the statistics page when a flow has produced rejects but keeps no pictures of them. */
export function ArchiveHint({ flow, ngCount }: { flow: Flow | undefined; ngCount: number }) {
  const { t } = useTranslation()
  const auth = useAuth()
  const toast = useToast()
  const { patch } = useFlowMutations()
  if (!flow || ngCount <= 0 || (flow.archive_policy?.mode ?? 'off') !== 'off') return null
  return (
    <div className="mb-4 flex flex-wrap items-center gap-3 rounded border border-warning/40 bg-warning/10 px-4 py-2.5 text-sm" data-testid="archive-hint">
      <Archive size={16} className="shrink-0 text-warning" aria-hidden />
      <span className="flex-1 min-w-60">{t('archive.hint', { count: ngCount })}</span>
      {auth.isEngineer ? (
        <Button size="xs" variant="primary" loading={patch.isPending}
          onClick={() => patch.mutate({ id: flow.id, archive_policy: { ...(flow.archive_policy ?? {}), mode: 'ng' } },
            { onSuccess: () => toast.success(t('archive.enabled')) })}
          data-testid="archive-enable">{t('archive.enable')}</Button>
      ) : null}
    </div>
  )
}

/** Thumbnails of one archived run; `open` comes from the row the user clicked. */
export function ArchivedImages({ run, open }: { run: RunReport; open: boolean }) {
  const { t } = useTranslation()
  const [zoom, setZoom] = useState<string | null>(null)
  const refs = Object.keys(run.images ?? {})
  if (!refs.length) return null
  return (
    <>
      <Badge tone="info" title={t('archive.hasImages', { count: refs.length })}><ImageIcon size={11} /> {refs.length}</Badge>
      {open ? (
        <div className="mt-2 flex flex-wrap justify-end gap-2" data-testid="archived-images">
          {refs.map((ref) => (
            <button key={ref} type="button" onClick={(e) => { e.stopPropagation(); setZoom(ref) }} title={ref}>
              <img src={imageUrl(ref, 120)} alt={ref} className="h-16 w-auto rounded border border-line" loading="lazy" />
            </button>
          ))}
        </div>
      ) : null}
      <Modal open={zoom !== null} onClose={() => setZoom(null)} title={t('archive.viewTitle')} size="lg">
        {zoom ? <img src={imageUrl(zoom, 1600)} alt={zoom} className="max-h-[70vh] w-full object-contain" /> : null}
      </Modal>
    </>
  )
}
