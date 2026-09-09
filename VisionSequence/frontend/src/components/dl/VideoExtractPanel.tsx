import { useEffect, useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Film, Square, Wand2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'

import { dlSampleUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useDlMutations, useDlVideoExtractStatus, useVisionVideos } from '@/lib/queries'
import type { DlProject } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

import { Button, Panel, Select, TextInput } from '@/components/ui'

export function VideoExtractPanel({ project }: { project: DlProject }) {
  const { t } = useTranslation()
  const toast = useToast()
  const queryClient = useQueryClient()
  const videos = useVisionVideos()
  const job = useDlVideoExtractStatus(project.id, true)
  const { startVideoExtract, stopVideoExtract } = useDlMutations()
  const [video, setVideo] = useState('')
  const [path, setPath] = useState('')
  const [model, setModel] = useState(project.last_asset_id || '')
  const [maxPerTrack, setMaxPerTrack] = useState('3')
  const [interval, setInterval] = useState('5')
  const [confirmFrames, setConfirmFrames] = useState('2')
  const [stride, setStride] = useState('1')
  const [edgeMargin, setEdgeMargin] = useState('0.03')
  const [split, setSplit] = useState<'train' | 'val' | 'test' | ''>('train')

  useEffect(() => {
    if (!video && videos.data?.length) setVideo(videos.data[0].name)
  }, [video, videos.data])

  useEffect(() => {
    if (job.data?.status === 'done' || job.data?.status === 'cancelled') {
      void queryClient.invalidateQueries({ queryKey: ['dl', 'project', project.id] })
      void queryClient.invalidateQueries({ queryKey: ['dl', 'samples', project.id] })
    }
  }, [job.data?.status, project.id, queryClient])

  const running = job.data?.status === 'running'
  const canStart = Boolean(video || path.trim())
  const percent = Math.round((job.data?.progress ?? 0) * 100)
  const options = useMemo(() => (videos.data ?? []).map((item) => ({
    value: item.name,
    label: `${item.name} (${formatBytes(item.size)})`,
  })), [videos.data])

  async function start() {
    try {
      await startVideoExtract.mutateAsync({
        projectId: project.id,
        video: video || undefined,
        video_path: path.trim() || undefined,
        params: {
          model: model.trim() || undefined,
          max_per_track: Number(maxPerTrack) || 3,
          frame_interval: Number(interval) || 5,
          confirm_frames: Number(confirmFrames) || 2,
          stride: Number(stride) || 1,
          margin_left: Number(edgeMargin) || 0,
          margin_right: Number(edgeMargin) || 0,
          margin_top: Number(edgeMargin) || 0,
          margin_bottom: Number(edgeMargin) || 0,
          split: split || undefined,
        },
      })
      toast.success(t('dl.videoExtractStarted'))
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  async function stop() {
    try {
      await stopVideoExtract.mutateAsync({ projectId: project.id })
    } catch (err) {
      toast.error(errorMessage(err))
    }
  }

  return (
    // 預設收合：展開時會把標記工作區整個往下推；有工作在跑（或跑過）時用 key 重掛載讓它自動展開
    <Panel
      key={job.data ? 'active' : 'idle'}
      collapsible
      defaultCollapsed={!job.data}
      testId="dl-video-extract"
      title={<span className="inline-flex items-center gap-2"><Film size={15} className="text-brand" />{t('dl.videoExtract')}</span>}
      description={job.data ? t('dl.videoExtractProgress', { percent, saved: job.data.saved }) : t('dl.videoExtractIdle')}
      bodyClassName="space-y-3 p-4"
    >
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          <Select label={t('dl.video')} value={video} onChange={(e) => setVideo(e.target.value)} options={options} placeholder={t('dl.videoPick')} disabled={running || videos.isLoading} />
          <TextInput label={t('dl.videoPath')} value={path} onChange={(e) => setPath(e.target.value)} disabled={running} />
          <TextInput label={t('dl.videoModel')} value={model} onChange={(e) => setModel(e.target.value)} disabled={running} />
          <TextInput label={t('dl.videoMaxPerTrack')} type="number" min={1} max={20} value={maxPerTrack} onChange={(e) => setMaxPerTrack(e.target.value)} disabled={running} />
          <TextInput label={t('dl.videoFrameInterval')} type="number" min={1} max={1000} value={interval} onChange={(e) => setInterval(e.target.value)} disabled={running} />
          <TextInput label={t('dl.videoConfirmFrames')} type="number" min={1} max={20} value={confirmFrames} onChange={(e) => setConfirmFrames(e.target.value)} disabled={running} />
          <TextInput label={t('dl.videoStride')} type="number" min={1} max={1000} value={stride} onChange={(e) => setStride(e.target.value)} disabled={running} />
          <TextInput label={t('dl.videoEdgeMargin')} type="number" min={0} max={0.5} step={0.01} value={edgeMargin} onChange={(e) => setEdgeMargin(e.target.value)} disabled={running} />
          <Select label={t('dl.videoSplit')} value={split} onChange={(e) => setSplit(e.target.value as typeof split)}
            options={[
              { value: 'train', label: t('dl.split.train') },
              { value: 'val', label: t('dl.split.val') },
              { value: 'test', label: t('dl.split.test') },
              { value: '', label: t('dl.split.unassigned') },
            ]} disabled={running} />
        </div>
        {job.data ? (
          <div className="space-y-2">
            <div className="h-1.5 overflow-hidden rounded-full bg-line">
              <div className="h-full bg-brand" style={{ width: `${percent}%` }} />
            </div>
            <div className="flex flex-wrap items-center gap-3 text-xs text-muted">
              <span>{t(`dl.videoStatus.${job.data.status}`)}</span>
              <span>{t('dl.videoFrames', { frame: job.data.frame, total: job.data.total_frames })}</span>
              <span>{t('dl.videoDuplicates', { count: job.data.duplicates })}</span>
            </div>
            {job.data.recent.length ? (
              <div className="flex gap-2 overflow-x-auto">
                {job.data.recent.map((id) => <img key={id} src={dlSampleUrl(id, 96)} alt="" className="h-14 w-20 rounded border border-line object-cover" />)}
              </div>
            ) : null}
          </div>
        ) : null}
        <div className="flex justify-end gap-2">
          {running ? <Button size="sm" onClick={() => void stop()} loading={stopVideoExtract.isPending}><Square size={13} /> {t('dl.videoStop')}</Button> : null}
          <Button size="sm" variant="primary" disabled={!canStart || running} loading={startVideoExtract.isPending} onClick={() => void start()} data-testid="dl-video-extract-start">
            <Wand2 size={13} /> {t('dl.videoStart')}
          </Button>
        </div>
    </Panel>
  )
}

function formatBytes(n: number): string {
  if (!n) return '0 B'
  let value = n
  for (const unit of ['B', 'KB', 'MB', 'GB']) {
    if (value < 1024 || unit === 'GB') return unit === 'B' ? `${value.toFixed(0)} ${unit}` : `${value.toFixed(1)} ${unit}`
    value /= 1024
  }
  return `${value.toFixed(1)} GB`
}
