/**
 * 擷取端（Capture client）相關 UI：
 * - `CaptureDownloadButton`：下載伺服端建置好的擷取端 zip（GET /vision/capture/download；未建置時停用並說明）。
 * - `CaptureSection`：外部整合頁「擷取端」分頁——程式資訊、伺服端擷取埠、設定步驟；已連線的擷取端與通道
 *   （解析度／像素格式／模式／fps／最近影格／使用中的來源／串流開關／預覽）。
 */
import { Fragment, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Download, Eye, Monitor, RefreshCw } from 'lucide-react'

import { Badge, Button, Card, CardBody, CardHeader, DetailRow, EmptyRow, IconButton, LoadingState, Modal, Switch, TBody, THead, Table, Td, Th, Tr } from '@/components/ui'
import { captureChannelPreviewUrl, downloadFile } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { formatBytes, formatDateTime, formatDateTimeFull } from '@/lib/format'
import { useCaptureClients, useCaptureDownloadInfo, useCaptureMutations, useIntegrationInfo } from '@/lib/queries'
import type { CaptureChannel, CaptureClient } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

export function CaptureDownloadButton({ size = 'md', variant = 'secondary' }: { size?: 'xs' | 'sm' | 'md'; variant?: 'secondary' | 'primary' }) {
  const { t } = useTranslation()
  const toast = useToast()
  const info = useCaptureDownloadInfo()
  const [busy, setBusy] = useState(false)
  const available = Boolean(info.data?.available)
  async function download() {
    if (!info.data?.available) return
    setBusy(true)
    try {
      await downloadFile('/vision/capture/download', info.data.filename)
      toast.success(t('sources.captureDownloaded', { name: info.data.filename }))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button size={size} variant={variant} icon={<Download size={size === 'xs' ? 12 : 15} />} loading={busy} disabled={!available}
      title={available ? `${info.data?.filename ?? ''} · ${formatBytes(info.data?.size ?? 0)}` : t('sources.captureUnavailable')} onClick={() => void download()} data-testid="capture-download">
      {t('sources.captureDownload')}{available && info.data?.version ? ` ${info.data.version}` : ''}
    </Button>
  )
}

function ageText(t: (k: string, o?: Record<string, unknown>) => string, ms: number | null): string {
  if (ms === null) return t('integration.capture.never')
  if (ms < 1000) return t('integration.capture.agoMs', { ms: Math.round(ms) })
  return t('integration.capture.agoS', { s: (ms / 1000).toFixed(1) })
}

function ChannelRows({ client, onPreview }: { client: CaptureClient; onPreview: (client: CaptureClient, channel: CaptureChannel) => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const { stream } = useCaptureMutations()
  const channels = client.channels.filter((c) => c.enabled)
  if (!channels.length) return <Tr><Td colSpan={7} className="text-xs text-subtle">{t('integration.capture.noChannels')}</Td></Tr>
  return (
    <>
      {channels.map((ch) => (
        <Tr key={`${client.name}/${ch.id}`}>
          <Td className="pl-8 text-sm">
            <span className="whitespace-nowrap font-medium">{ch.label}</span> <span className="font-mono text-[11px] text-muted">{ch.id}</span>
            {ch.last_error ? <span className="block truncate text-xs text-critical" title={ch.last_error}>{ch.last_error}</span> : null}
          </Td>
          <Td className="whitespace-nowrap text-xs text-muted">{ch.width}×{ch.height} · {ch.pixel_format}{ch.roi && ch.full && (ch.roi.w !== ch.full.w || ch.roi.h !== ch.full.h) ? ` · ROI ${ch.roi.x},${ch.roi.y}` : ''}</Td>
          <Td className="whitespace-nowrap text-xs"><Badge tone={ch.mode === 'stream' ? 'info' : 'neutral'}>{t(`integration.capture.modes.${ch.mode}`, { defaultValue: ch.mode })}</Badge>{ch.shm ? <Badge className="ml-1">{t('integration.capture.local')}</Badge> : null}</Td>
          <Td className="tnum whitespace-nowrap text-xs">
            <span title={ch.recv_ms ? t('integration.capture.recvMs', { ms: ch.recv_ms.toFixed(1) }) : undefined}>
              {ch.fps ? `${ch.fps.toFixed(1)} fps` : '—'}{ch.bytes_per_s ? <span className="text-muted"> · {formatBytes(ch.bytes_per_s)}/s</span> : null}
            </span>
          </Td>
          <Td className="tnum whitespace-nowrap text-xs">{ageText(t, ch.last_frame_age_ms)}{ch.frames ? <span className="text-muted"> · {t('integration.capture.frames', { count: ch.frames })}</span> : null}</Td>
          <Td className="max-lg:hidden text-xs text-muted">{ch.in_use_by.length ? ch.in_use_by.join('、') : '—'}</Td>
          <Td align="right">
            <span className="inline-flex items-center justify-end gap-2">
              <Switch checked={ch.streaming} label={t('integration.capture.stream')} onChange={(v) => stream.mutate({ client: client.name, channel: ch.id, enabled: v }, { onError: (e) => toast.error(errorMessage(e)) })} />
              <IconButton label={t('integration.capture.preview')} onClick={() => onPreview(client, ch)}><Eye size={15} /></IconButton>
            </span>
          </Td>
        </Tr>
      ))}
    </>
  )
}

export function CaptureSection() {
  const { t } = useTranslation()
  const info = useIntegrationInfo()
  const download = useCaptureDownloadInfo()
  const clients = useCaptureClients(true)
  const [preview, setPreview] = useState<{ client: CaptureClient; channel: CaptureChannel; url: string } | null>(null)
  const steps = t('integration.capture.stepLines', { returnObjects: true }) as unknown as string[]
  const host = info.data?.capture_host && info.data.capture_host !== '0.0.0.0' ? info.data.capture_host : info.data?.host ?? ''
  const port = info.data?.capture_port ?? clients.data?.port ?? 9100
  const listening = clients.data?.listening ?? info.data?.capture_listening ?? false
  const items = clients.data?.items ?? []
  return (
    <div className="grid gap-4 2xl:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]" data-testid="capture-section">
      <Card>
        <CardHeader title={<span className="flex items-center gap-2"><Monitor size={16} className="text-brand" />{t('integration.capture.title')}</span>} description={t('integration.capture.intro')} />
        <CardBody className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <CaptureDownloadButton variant="primary" />
            {download.data?.available ? <span className="text-xs text-muted">{download.data.filename} · {formatBytes(download.data.size)}</span> : <span className="text-xs text-warning">{t('integration.capture.unavailable')}</span>}
          </div>
          {download.data?.available ? (
            <div className="rounded-md border border-line bg-surface px-3 py-1 text-xs">
              <DetailRow label={t('integration.capture.version')}>{download.data.version}</DetailRow>
              <DetailRow label={t('integration.capture.builtAt')}><span title={formatDateTimeFull(download.data.built_at)}>{formatDateTime(download.data.built_at)}</span></DetailRow>
              <DetailRow label="SHA-256" mono><span className="text-[11px]">{download.data.sha256}</span></DetailRow>
            </div>
          ) : null}
          <div className="rounded-md border border-line bg-surface px-3 py-2 text-sm">
            <span className="text-muted">{t('integration.capture.serverAddress')}：</span><code className="font-mono">{host}:{port}</code>{' '}
            <Badge tone={listening ? 'ok' : 'warning'}>{listening ? t('integration.info.listening') : t('integration.info.notListening')}</Badge>
          </div>
          <div>
            <p className="mb-1 text-sm font-medium">{t('integration.capture.stepsTitle')}</p>
            <ol className="list-decimal space-y-1 pl-5 text-sm text-muted">
              {steps.map((line, i) => <li key={i}>{line}</li>)}
            </ol>
          </div>
          <p className="text-xs text-subtle">{t('integration.capture.docs')}</p>
        </CardBody>
      </Card>
      <Card className="overflow-hidden">
        <CardHeader title={t('integration.capture.clients')} description={t('integration.capture.clientCount', { count: items.length })}
          actions={<Button size="xs" icon={<RefreshCw size={12} />} loading={clients.isFetching} onClick={() => void clients.refetch()}>{t('common.refresh')}</Button>} />
        {clients.isPending ? (
          <LoadingState compact />
        ) : (
          <Table>
            <THead>
              <Th>{t('integration.capture.cols.name')}</Th>
              <Th>{t('integration.capture.cols.size')}</Th>
              <Th>{t('integration.capture.cols.mode')}</Th>
              <Th>{t('integration.capture.cols.fps')}</Th>
              <Th>{t('integration.capture.cols.lastFrame')}</Th>
              <Th className="max-lg:hidden">{t('integration.capture.cols.usedBy')}</Th>
              <Th align="right">{t('common.actions')}</Th>
            </THead>
            <TBody>
              {items.length === 0 ? (
                <EmptyRow colSpan={7} message={t('integration.capture.noClients')} />
              ) : (
                items.map((c) => (
                  <Fragment key={c.name}>
                    <Tr>
                      <Td colSpan={6} className="bg-surface-muted/60 text-sm">
                        <span className="font-semibold">{c.name}</span>
                        <span className="ml-2 text-xs text-muted">{c.hostname} · {c.address} · v{c.version}</span>
                        <Badge tone={c.local ? 'ok' : 'info'} className="ml-2">{c.local ? t('integration.capture.local') : t('integration.capture.remote')}</Badge>
                      </Td>
                      <Td className="bg-surface-muted/60 text-xs text-muted" align="right"><span title={formatDateTimeFull(c.connected_at)}>{formatDateTime(c.connected_at)}</span></Td>
                    </Tr>
                    <ChannelRows client={c} onPreview={(client, channel) => setPreview({ client, channel, url: captureChannelPreviewUrl(client.name, channel.id) })} />
                  </Fragment>
                ))
              )}
            </TBody>
          </Table>
        )}
      </Card>
      <Modal open={preview !== null} onClose={() => setPreview(null)} size="lg" title={t('integration.capture.previewTitle', { client: preview?.client.name ?? '', channel: preview?.channel.label ?? '' })}
        footer={<Button onClick={() => preview && setPreview({ ...preview, url: captureChannelPreviewUrl(preview.client.name, preview.channel.id) })}>{t('common.refresh')}</Button>}>
        {preview ? (
          <div className="flex min-h-64 items-center justify-center rounded-lg bg-viewer">
            <img src={preview.url} alt="" className="max-h-[70vh] max-w-full object-contain" />
          </div>
        ) : null}
      </Modal>
    </div>
  )
}
