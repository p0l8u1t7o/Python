/** 資產：影像縮圖網格、上傳（image/model/file）、刪除。 */
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FileBox, Images, LayoutGrid, ListTree, Pencil, Trash2, Upload } from 'lucide-react'

import { AssetTree } from '@/components/assets/AssetTree'
import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, ConfirmDialog, EmptyState, ErrorState, GROUP_ALL, GroupChips, GroupSelect, LoadingState, Modal, PageHeader, SegmentedControl, Select, TextInput, matchGroup } from '@/components/ui'
import { GroupManager } from '@/components/GroupManager'
import { assetUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useAssetMutations, useAssets, useGroups } from '@/lib/queries'
import type { Asset } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

import { formatSize } from '@/components/assets/AssetTree'

const VIEW_KEY = 'vs.assetsView'
type AssetView = 'cards' | 'tree'

function storedView(): AssetView {
  try {
    return localStorage.getItem(VIEW_KEY) === 'tree' ? 'tree' : 'cards'
  } catch {
    return 'cards'
  }
}

export function AssetsPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const [kindFilter, setKindFilter] = useState('')
  const assets = useAssets(kindFilter)
  const { uploadFile, patch, remove } = useAssetMutations()
  const [uploading, setUploading] = useState(false)
  const [form, setForm] = useState<{ file: File | null; kind: Asset['kind']; name: string; group: string }>({ file: null, kind: 'image', name: '', group: '' })
  const [pendingDelete, setPendingDelete] = useState<Asset | null>(null)
  const [groupFilter, setGroupFilter] = useState(GROUP_ALL)
  const [managingGroups, setManagingGroups] = useState(false)
  const [view, setView] = useState<AssetView>(storedView)
  const groups = useGroups('asset')
  //: 編輯名稱／群組的小 Modal
  const [editing, setEditing] = useState<{ asset: Asset; name: string; group: string } | null>(null)

  async function onUpload() {
    if (!form.file) return
    try {
      await uploadFile.mutateAsync({ file: form.file, kind: form.kind, name: form.name, group: form.group })
      toast.success(t('assets.uploaded'))
      setUploading(false)
      setForm({ file: null, kind: 'image', name: '', group: '' })
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

  async function onSaveEdit() {
    if (!editing) return
    try {
      await patch.mutateAsync({ id: editing.asset.id, name: editing.name.trim() || editing.asset.name, group: editing.group })
      setEditing(null)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  return (
    <Page>
      <PageHeader
        title={t('assets.title')}
        description={t('assets.subtitle')}
        actions={
          <>
            <SegmentedControl
              value={view}
              onChange={(v) => { setView(v); try { localStorage.setItem(VIEW_KEY, v) } catch { /* 忽略 */ } }}
              options={[
                { value: 'cards', label: <span className="flex items-center gap-1"><LayoutGrid size={13} /> {t('assets.views.cards')}</span> },
                { value: 'tree', label: <span className="flex items-center gap-1"><ListTree size={13} /> {t('assets.views.tree')}</span> },
              ]}
            />
            <Select value={kindFilter} onChange={(e) => setKindFilter(e.target.value)} placeholder={t('common.none')} aria-label={t('assets.kind')} options={kindOptions} className="w-36" />
            <Button onClick={() => setManagingGroups(true)} data-testid="manage-groups">{t('groups.manage')}</Button>
            <Button variant="primary" icon={<Upload size={15} />} onClick={() => setUploading(true)}>{t('assets.upload')}</Button>
          </>
        }
      />
      <GroupChips items={assets.data?.items ?? []} value={groupFilter} onChange={setGroupFilter} />
      {assets.isPending ? (
        <LoadingState />
      ) : assets.isError ? (
        <ErrorState error={assets.error} onRetry={() => void assets.refetch()} />
      ) : assets.data.items.length === 0 ? (
        <Card><EmptyState icon={<Images className="size-6" />} title={t('assets.empty')} /></Card>
      ) : view === 'tree' ? (
        <AssetTree items={assets.data.items.filter((a) => matchGroup(a, groupFilter))}
          onEdit={(asset) => setEditing({ asset, name: asset.name, group: asset.group })} onDelete={setPendingDelete} />
      ) : (
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
          {assets.data.items.filter((a) => matchGroup(a, groupFilter)).map((asset) => (
            <Card key={asset.id} className="overflow-hidden">
              <div className="flex aspect-square items-center justify-center bg-viewer">
                {asset.kind === 'image' ? <img src={assetUrl(asset.id, 256)} alt={asset.name} className="max-h-full max-w-full object-contain" loading="lazy" /> : <FileBox className="size-10 text-subtle" />}
              </div>
              <div className="p-2.5">
                <p className="truncate text-sm font-medium" title={asset.name}>{asset.name}</p>
                <div className="mt-1 flex items-center justify-between text-xs text-muted">
                  <span className="flex min-w-0 items-center gap-1.5">
                    <Badge tone={asset.kind === 'image' ? 'info' : asset.kind === 'model' ? 'brand' : 'neutral'}>{t(`assets.kinds.${asset.kind}`)}</Badge>
                    {asset.group ? <Badge>{asset.group}</Badge> : null}
                    <span className="tnum">{formatSize(asset.size)}</span>
                  </span>
                  <span className="flex shrink-0">
                    <button type="button" className="btn-icon" title={t('assets.editGroup')} onClick={() => setEditing({ asset, name: asset.name, group: asset.group })}>
                      <Pencil size={14} />
                    </button>
                    <button type="button" className="btn-icon" title={t('common.delete')} onClick={() => setPendingDelete(asset)}>
                      <Trash2 size={14} className="text-critical" />
                    </button>
                  </span>
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
          <GroupSelect label={t('common.group')} value={form.group} groups={groups.data ?? []} onChange={(v) => setForm({ ...form, group: v })} />
        </div>
      </Modal>

      <Modal open={editing !== null} onClose={() => setEditing(null)} title={t('assets.editGroup')}
        footer={<><Button onClick={() => setEditing(null)}>{t('common.cancel')}</Button>
          <Button variant="primary" loading={patch.isPending} onClick={() => void onSaveEdit()}>{t('common.save')}</Button></>}>
        {editing ? (
          <div className="space-y-3">
            <TextInput label={t('common.name')} value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} />
            <GroupSelect label={t('common.group')} value={editing.group} groups={groups.data ?? []} onChange={(v) => setEditing({ ...editing, group: v })} />
          </div>
        ) : null}
      </Modal>

      <GroupManager kind="asset" open={managingGroups} onClose={() => setManagingGroups(false)} />
      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void onDelete()} title={t('assets.deleteTitle')} message={t('assets.deleteMessage', { name: pendingDelete?.name ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </Page>
  )
}
