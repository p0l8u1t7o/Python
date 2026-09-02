/** 影像來源 CRUD。config 欄位依 kind 的 fields 顯示（伺服器 /sources/kinds 給）。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Camera, Eye, FolderOpen, Pencil, Plus, RefreshCw, Trash2, Upload } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, Checkbox, ConfirmDialog, EmptyRow, ErrorState, GROUP_ALL, GroupChips, GroupSelect, IconButton, LoadingState, Modal, PageHeader, Select, Switch, TBody, THead, Table, Td, TextInput, Th, Tr, matchGroup } from '@/components/ui'
import { GroupManager } from '@/components/GroupManager'
import { api, sourcePreviewUrl } from '@/lib/api'
import { FsBrowser } from '@/components/FsBrowser'
import { errorMessage } from '@/lib/errors'
import { useGroups, useSourceKinds, useSourceMutations, useSources, type SourceBody } from '@/lib/queries'
import type { ImageSource } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'

/** 每個 config 欄位的輸入型態。 */
const FIELD_TYPE: Record<string, 'text' | 'number' | 'boolean' | 'select'> = {
  path: 'text',
  loop: 'boolean',
  sort: 'select',
  pattern: 'text',
  index: 'number',
  width: 'number',
  height: 'number',
  fps: 'number',
  seed: 'number',
  defect_rate: 'number',
  class: 'text',
}
const FIELD_DEFAULT: Record<string, unknown> = { loop: true, sort: 'name', pattern: '*.png;*.jpg;*.bmp', index: 0, width: 640, height: 480, fps: 0, seed: 0, defect_rate: 0.3 }

function ConfigField({ kind, field, value, onChange, onBrowse, cameras, onScanCameras, scanning }: {
  kind: string
  field: string
  value: unknown
  onChange: (v: unknown) => void
  onBrowse?: (mode: 'dir' | 'file') => void
  cameras?: { index: number; width: number; height: number; in_use_by: string }[] | null
  onScanCameras?: () => void
  scanning?: boolean
}) {
  const { t } = useTranslation()
  const label = t(`sources.fields.${field}`, { defaultValue: field })
  const type = FIELD_TYPE[field] ?? 'text'
  // folder/file 的 path：可開伺服器檔案瀏覽器選路徑
  if (field === 'path' && (kind === 'folder' || kind === 'file') && onBrowse) {
    return (
      <div className="flex items-end gap-2">
        <TextInput label={label} className="font-mono" value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
        <Button title={t('fs.browse')} onClick={() => onBrowse(kind === 'folder' ? 'dir' : 'file')} data-testid="cfg-browse">
          <FolderOpen size={14} /> {t('fs.browse')}
        </Button>
      </div>
    )
  }
  // usb 的 index：掃描伺服器上的相機供選擇
  if (field === 'index' && kind === 'usb' && onScanCameras) {
    return (
      <div className="space-y-1.5">
        <div className="flex items-end gap-2">
          <TextInput label={label} type="number" value={value === undefined || value === null ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />
          <Button loading={scanning} onClick={onScanCameras} title={t('sources.scanHint')} data-testid="cfg-scan">
            <RefreshCw size={14} /> {t('sources.scanCameras')}
          </Button>
        </div>
        {cameras ? (
          cameras.length ? (
            <div className="flex flex-wrap gap-1.5">
              {cameras.map((c) => (
                <button key={c.index} type="button" onClick={() => onChange(c.index)} aria-pressed={Number(value) === c.index}
                  className={`rounded-md border px-2.5 py-1.5 text-xs transition-colors ${Number(value) === c.index ? 'border-transparent bg-brand text-on-brand' : 'border-line hover:bg-surface-muted'}`}
                  data-testid={`cfg-cam-${c.index}`}>
                  {t('sources.cameraN', { n: c.index })}{c.width ? ` · ${c.width}×${c.height}` : ''}{c.in_use_by ? ` · ${t('sources.inUseBy', { name: c.in_use_by })}` : ''}
                </button>
              ))}
            </div>
          ) : (
            <p className="text-xs text-subtle">{t('sources.noCameras')}</p>
          )
        ) : null}
      </div>
    )
  }
  if (type === 'boolean') return <Checkbox label={label} checked={Boolean(value)} onChange={onChange} />
  if (type === 'select' && field === 'sort') {
    return <Select label={label} value={String(value ?? 'name')} onChange={(e) => onChange(e.target.value)} options={['name', 'mtime', 'random'].map((v) => ({ value: v, label: t(`sources.sortOptions.${v}`) }))} />
  }
  if (field === 'pattern' && kind === 'synthetic') {
    return <Select label={label} value={String(value ?? 'dots')} onChange={(e) => onChange(e.target.value)} options={['dots', 'bars', 'random'].map((p) => ({ value: p, label: t(`sources.patterns.${p}`) }))} />
  }
  if (type === 'number') return <TextInput label={label} type="number" step={field === 'defect_rate' ? 0.05 : 1} value={value === undefined || value === null ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />
  return <TextInput label={label} value={String(value ?? '')} onChange={(e) => onChange(e.target.value)} />
}

export function SourcesPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const sources = useSources()
  const kinds = useSourceKinds()
  const { create, patch, remove, push } = useSourceMutations()
  const [editing, setEditing] = useState<{ id: number | null; body: SourceBody } | null>(null)
  const [groupFilter, setGroupFilter] = useState(GROUP_ALL)
  const [managingGroups, setManagingGroups] = useState(false)
  const groups = useGroups('source')
  const [pendingDelete, setPendingDelete] = useState<ImageSource | null>(null)
  const [preview, setPreview] = useState<{ source: ImageSource; url: string } | null>(null)
  const [browsing, setBrowsing] = useState<'dir' | 'file' | null>(null)
  const [cameras, setCameras] = useState<{ index: number; width: number; height: number; in_use_by: string }[] | null>(null)
  const [scanning, setScanning] = useState(false)

  async function scanCameras() {
    setScanning(true)
    try {
      const r = await api.get<{ items: { index: number; width: number; height: number; in_use_by: string }[] }>('/vision/sources/usb-scan')
      setCameras(r.items)
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setScanning(false)
    }
  }

  const kindList = kinds.data ?? []
  const fieldsFor = useMemo(() => new Map(kindList.map((k) => [k.kind, k.fields])), [kindList])

  function openCreate() {
    const kind = kindList[0]?.kind ?? 'folder'
    setEditing({ id: null, body: { name: '', kind, config: defaultsFor(kind), is_enabled: true, group: groupFilter === GROUP_ALL || groupFilter === '__none__' ? '' : groupFilter } })
  }
  function defaultsFor(kind: string): Record<string, unknown> {
    const out: Record<string, unknown> = {}
    for (const f of fieldsFor.get(kind) ?? []) if (f in FIELD_DEFAULT) out[f] = FIELD_DEFAULT[f]
    if (kind === 'synthetic') out.pattern = 'dots'
    return out
  }

  async function onSave() {
    if (!editing) return
    if (!editing.body.name.trim()) return toast.error(t('flows.nameRequired'))
    try {
      if (editing.id === null) {
        await create.mutateAsync(editing.body)
        toast.success(t('sources.created'))
      } else {
        await patch.mutateAsync({ id: editing.id, ...editing.body })
        toast.success(t('sources.updated'))
      }
      setEditing(null)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function onDelete() {
    if (!pendingDelete) return
    try {
      await remove.mutateAsync(pendingDelete.id)
      toast.success(t('sources.deleted'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setPendingDelete(null)
    }
  }

  async function onPush(source: ImageSource, file: File | undefined) {
    if (!file) return
    try {
      await push.mutateAsync({ id: source.id, file })
      toast.success(t('common.saved'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const body = editing?.body
  return (
    <Page>
      <PageHeader title={t('sources.title')} description={t('sources.subtitle')} actions={<><Button onClick={() => setManagingGroups(true)} data-testid="manage-groups">{t('groups.manage')}</Button><Button variant="primary" icon={<Plus size={15} />} onClick={openCreate}>{t('sources.create')}</Button></>} />
      <GroupChips items={sources.data?.items ?? []} value={groupFilter} onChange={setGroupFilter} />
      <Card className="overflow-hidden">
        {sources.isPending ? (
          <LoadingState />
        ) : sources.isError ? (
          <ErrorState error={sources.error} onRetry={() => void sources.refetch()} />
        ) : (
          <Table>
            <THead>
              <Th>{t('common.actions')}</Th>
              <Th>{t('common.name')}</Th>
              <Th>{t('common.group')}</Th>
              <Th>{t('sources.kind')}</Th>
              <Th>{t('sources.config')}</Th>
              <Th>{t('sources.status')}</Th>
              <Th align="center">{t('common.enabled')}</Th>
            </THead>
            <TBody>
              {sources.data.items.length === 0 ? (
                <EmptyRow colSpan={7} message={<span className="inline-flex flex-col items-center gap-1"><Camera className="size-5" />{t('sources.empty')}</span>} />
              ) : (
                sources.data.items.filter((s) => matchGroup(s, groupFilter)).map((s) => (
                  <Tr key={s.id}>
                    <Td>
                      <span className="inline-flex gap-1">
                        {s.kind === 'upload' ? (
                          <label className="btn-icon cursor-pointer" title={t('common.upload')}>
                            <Upload size={15} />
                            <input type="file" accept="image/*" className="hidden" onChange={(e) => void onPush(s, e.target.files?.[0])} />
                          </label>
                        ) : null}
                        <IconButton label={t('sources.preview')} onClick={() => setPreview({ source: s, url: sourcePreviewUrl(s.id) })}><Eye size={15} /></IconButton>
                        <IconButton label={t('common.edit')} onClick={() => setEditing({ id: s.id, body: { name: s.name, kind: s.kind, config: { ...s.config }, is_enabled: s.is_enabled, group: s.group } })}><Pencil size={15} /></IconButton>
                        <IconButton label={t('common.delete')} onClick={() => setPendingDelete(s)}><Trash2 size={15} className="text-critical" /></IconButton>
                      </span>
                    </Td>
                    <Td className="font-medium">{s.name} <span className="text-xs text-muted">#{s.id}</span></Td>
                    <Td>{s.group ? <Badge>{s.group}</Badge> : <span className="text-xs text-subtle">—</span>}</Td>
                    <Td><Badge tone="info">{kindList.find((k) => k.kind === s.kind)?.label ?? s.kind}</Badge></Td>
                    <Td><code className="block max-w-xs truncate font-mono text-xs text-muted" title={JSON.stringify(s.config)}>{JSON.stringify(s.config)}</code></Td>
                    <Td><code className="block max-w-xs truncate font-mono text-xs text-muted" title={JSON.stringify(s.status)}>{JSON.stringify(s.status)}</code></Td>
                    <Td align="center"><Switch checked={s.is_enabled} onChange={(v) => patch.mutate({ id: s.id, is_enabled: v })} /></Td>
                  </Tr>
                ))
              )}
            </TBody>
          </Table>
        )}
      </Card>

      <Modal
        open={editing !== null}
        onClose={() => setEditing(null)}
        title={editing?.id === null ? t('sources.create') : t('common.edit')}
        footer={
          <>
            <Button onClick={() => setEditing(null)}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={create.isPending || patch.isPending} onClick={() => void onSave()}>{t('common.save')}</Button>
          </>
        }
      >
        {body ? (
          <div className="space-y-3">
            <TextInput label={t('common.name')} required autoFocus value={body.name} onChange={(e) => setEditing({ ...editing!, body: { ...body, name: e.target.value } })} />
            <GroupSelect label={t('common.group')} value={body.group ?? ''} groups={groups.data ?? []}
              onChange={(v) => setEditing({ ...editing!, body: { ...body, group: v } })} />
            <Select label={t('sources.kind')} value={body.kind} onChange={(e) => setEditing({ ...editing!, body: { ...body, kind: e.target.value, config: defaultsFor(e.target.value) } })} options={kindList.map((k) => ({ value: k.kind, label: k.label }))} />
            {(fieldsFor.get(body.kind) ?? []).map((field) => (
              <ConfigField key={field} kind={body.kind} field={field} value={body.config[field]}
                onChange={(v) => setEditing({ ...editing!, body: { ...body, config: { ...body.config, [field]: v } } })}
                onBrowse={(mode) => setBrowsing(mode)} cameras={cameras} onScanCameras={() => void scanCameras()} scanning={scanning} />
            ))}
            <Checkbox label={t('common.enabled')} checked={body.is_enabled} onChange={(v) => setEditing({ ...editing!, body: { ...body, is_enabled: v } })} />
          </div>
        ) : null}
      </Modal>

      <Modal open={preview !== null} onClose={() => setPreview(null)} title={t('sources.previewTitle', { name: preview?.source.name ?? '' })} size="lg" footer={<Button onClick={() => preview && setPreview({ ...preview, url: sourcePreviewUrl(preview.source.id) })}>{t('common.refresh')}</Button>}>
        {preview ? (
          <div className="flex min-h-64 items-center justify-center rounded-lg bg-viewer">
            <img src={preview.url} alt="" className="max-h-[70vh] max-w-full object-contain" />
          </div>
        ) : null}
      </Modal>

      <GroupManager kind="source" open={managingGroups} onClose={() => setManagingGroups(false)} />
      <FsBrowser open={browsing !== null} onClose={() => setBrowsing(null)} mode={browsing ?? 'dir'}
        initial={String(body?.config.path ?? '')}
        onPick={(picked) => { if (editing && body) setEditing({ ...editing, body: { ...body, config: { ...body.config, path: picked } } }) }} />
      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void onDelete()} title={t('sources.deleteTitle')} message={t('sources.deleteMessage', { name: pendingDelete?.name ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </Page>
  )
}
