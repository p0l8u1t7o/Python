/** 單張檢視：以持久化影像重跑一次（POST /batch/runs/{id}/rows/{index}/preview）取得標記，顯示在影像視窗。 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { formatValue } from '@/components/editor/ResultsPanel'
import { LoadingState, Modal, StatusBadge } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { imageUrl } from '@/lib/api'
import { previewRow, type BatchRun, type BatchSet } from '@/lib/batch'
import { errorMessage } from '@/lib/errors'
import type { FlowGraph, RunReport } from '@/lib/types'
import { sourceRefOf } from '@/pages/FlowEditorPage'
import { useToast } from '@/providers/ToastProvider'

export function BatchRowPreviewModal({ run, set, index, graph, onClose }: { run: BatchRun | null; set: BatchSet | null; index: number | null; graph: FlowGraph | null; onClose: () => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const [report, setReport] = useState<RunReport | null>(null)
  const [loading, setLoading] = useState(false)
  const open = run !== null && index !== null

  useEffect(() => {
    if (!open || !run || index === null) return
    let alive = true
    setLoading(true)
    setReport(null)
    previewRow(run.id, index, graph).then((r) => { if (alive) setReport(r) }).catch((e) => { if (alive) { toast.error(errorMessage(e)); onClose() } }).finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, run?.id, index])

  const payloads = useMemo(() => new Map(((graph ?? run?.graph)?.nodes ?? []).map((n) => [n.id, n])), [graph, run])
  const ref = report ? sourceRefOf(report, payloads) : null
  const size = useMemo(() => {
    if (!report) return { w: 0, h: 0 }
    for (const rep of Object.values(report.nodes)) {
      const img = Object.values(rep.outputs ?? {}).find((v) => v && typeof v === 'object' && 'width' in (v as object)) as { width: number; height: number } | undefined
      if (img) return { w: img.width, h: img.height }
    }
    return { w: 0, h: 0 }
  }, [report])
  const overlays = report ? Object.values(report.nodes).flatMap((n) => n.overlays ?? []) : []
  const image = set?.images?.find((im) => im.index === index)
  return (
    <Modal open={open} onClose={onClose} size="xl" title={t('batchPage.preview', { n: (index ?? 0) + 1 })} description={image?.name}>
      {loading || !report ? <LoadingState compact /> : (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <StatusBadge status={report.status} />
            <span className="tnum text-muted">{Math.round(report.duration_ms)} ms</span>
            {report.error ? <span className="text-critical">{report.error}</span> : null}
            <span className="font-mono text-muted">{Object.entries(report.outputs ?? {}).slice(0, 6).map(([k, v]) => `${k}=${formatValue(v)}`).join('  ')}</span>
          </div>
          <div className="h-[65vh] rounded-lg bg-viewer">
            <ImageViewer src={ref ? imageUrl(ref, 1600) : null} imageWidth={size.w} imageHeight={size.h} overlays={overlays} toolbar className="h-full w-full"
              badge={{ text: t(`status.${report.status}`), tone: report.status === 'ok' ? 'ok' : report.status === 'ng' || report.status === 'failed' ? 'ng' : 'neutral' }} />
          </div>
        </div>
      )}
    </Modal>
  )
}
