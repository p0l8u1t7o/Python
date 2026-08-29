/** 資產：影像縮圖網格、上傳（image/model/file）、刪除。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileBox, Images, Trash2, Upload } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, LoadingState, Modal, PageHeader, Select, TextInput } from '@/components/ui'
import { assetUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useAssetMutations, useAssets } from '@/lib/queries'
import type { Asset } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1048576).toFixed(1)} MB`
}

export function AssetsPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const [kindFilter, setKindFilter] = useState('')
  const assets = useAssets(kindFilter)
  const { uploadFile, remove } = useAssetMutations()
  const [uploading, setUploading] = useState(false)
  const [form, setForm] = useState<{ file: File | null; kind: Asset['kind']; name: string }>({ file: null, kind: 'image', name: '' })
  const [pendingDelete, setPendingDelete] = useState<Asset | null>(null)

  async function onUpload() {
    if (!form.file) return
    try {
      await uploadFile.mutateAsync({ file: form.file, kind: form.kind, name: form.name })
      toast.success(t('assets.uploaded'))
      setUploading(false)
      setForm({ file: null, kind: 'image', name: '' })
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function onDelete() {
    if (!pendingDelete) return
    try {
      await remove.mutateAsync(pendingDelete.id)
      toast.success(t('assets.deleted'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setPendingDelete(null)
    }
  }

  const kindOptions = (['image', 'model', 'file'] as const).map((k) => ({ value: k, label: t(`assets.kinds.${k}`) }))

  return (
    <Page>
      <PageHeader
        title={t('assets.title')}
        description={t('assets.subtitle')}
        actions={
          <>
            <Select value={kindFilter} onChange={(e) => setKindFilter(e.target.value)} placeholder={t('common.none')} options={kindOptions} className="w-36" />
            <Button variant="primary" icon={<Upload size={15} />} onClick={() => setUploading(true)}>{t('assets.upload')}</Button>
          </>
        }
      />
      {assets.isPending ? (
        <LoadingState />
      ) : assets.isError ? (
        <ErrorState error={assets.error} onRetry={() => void assets.refetch()} />
      ) : assets.data.items.length === 0 ? (
        <Card><EmptyState icon={<Images className="size-6" />} title={t('assets.empty')} /></Card>
      ) : (
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {assets.data.items.map((asset) => (
            <Card key={asset.id} className="overflow-hidden">
              <div className="flex aspect-square items-center justify-center bg-viewer">
                {asset.kind === 'image' ? <img src={assetUrl(asset.id, 256)} alt={asset.name} className="max-h-full max-w-full object-contain" loading="lazy" /> : <FileBox className="size-10 text-subtle" />}
              </div>
              <div className="p-2.5">
                <p className="truncate text-sm font-medium" title={asset.name}>{asset.name}</p>
                <div className="mt-1 flex items-center justify-between text-xs text-muted">
                  <span className="flex items-center gap-1.5">
                    <Badge tone={asset.kind === 'image' ? 'info' : asset.kind === 'model' ? 'brand' : 'neutral'}>{t(`assets.kinds.${asset.kind}`)}</Badge>
                    <span className="tnum">{formatSize(asset.size)}</span>
                    {typeof asset.meta.width === 'number' ? <span className="tnum">{String(asset.meta.width)}×{String(asset.meta.height)}</span> : null}
                  </span>
                  <button type="button" className="btn-icon" title={t('common.delete')} onClick={() => setPendingDelete(asset)}>
                    <Trash2 size={14} className="text-critical" />
                  </button>
                </div>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Modal
        open={uploading}
        onClose={() => setUploading(false)}
        title={t('assets.upload')}
        footer={
          <>
            <Button onClick={() => setUploading(false)}>{t('common.cancel')}</Button>
            <Button variant="primary" disabled={!form.file} loading={uploadFile.isPending} onClick={() => void onUpload()}>{t('common.upload')}</Button>
          </>
        }
      >
        <div className="space-y-3">
          <Select label={t('assets.kind')} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as Asset['kind'] })} options={kindOptions} />
          <div>
            <span className="label">{t('assets.file')}</span>
            <input type="file" className="input" accept={form.kind === 'image' ? 'image/*' : undefined} onChange={(e) => setForm({ ...form, file: e.target.files?.[0] ?? null })} />
          </div>
          <TextInput label={t('common.name')} value={form.name} placeholder={form.file?.name ?? ''} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </div>
      </Modal>

      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void onDelete()} title={t('assets.deleteTitle')} message={t('assets.deleteMessage', { name: pendingDelete?.name ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </Page>
  )
}
