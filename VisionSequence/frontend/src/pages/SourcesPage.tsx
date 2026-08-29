/** 影像來源 CRUD。config 欄位依 kind 的 fields 顯示（伺服器 /sources/kinds 給）。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Camera, Eye, Pencil, Plus, Trash2, Upload } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { Badge, Button, Card, Checkbox, ConfirmDialog, EmptyRow, ErrorState, IconButton, LoadingState, Modal, PageHeader, Select, Switch, TBody, THead, Table, Td, TextInput, Th, Tr } from '@/components/ui'
import { sourcePreviewUrl } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useSourceKinds, useSourceMutations, useSources, type SourceBody } from '@/lib/queries'
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

function ConfigField({ kind, field, value, onChange }: { kind: string; field: string; value: unknown; onChange: (v: unknown) => void }) {
  const { t } = useTranslation()
  const label = t(`sources.fields.${field}`, { defaultValue: field })
  const type = FIELD_TYPE[field] ?? 'text'
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
  const [pendingDelete, setPendingDelete] = useState<ImageSource | null>(null)
  const [preview, setPreview] = useState<{ source: ImageSource; url: string } | null>(null)

  const kindList = kinds.data ?? []
  const fieldsFor = useMemo(() => new Map(kindList.map((k) => [k.kind, k.fields])), [kindList])

  function openCreate() {
    const kind = kindList[0]?.kind ?? 'folder'
    setEditing({ id: null, body: { name: '', kind, config: defaultsFor(kind), is_enabled: true } })
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
      <PageHeader title={t('sources.title')} description={t('sources.subtitle')} actions={<Button variant="primary" icon={<Plus size={15} />} onClick={openCreate}>{t('sources.create')}</Button>} />
      <Card className="overflow-hidden">
        {sources.isPending ? (
          <LoadingState />
        ) : sources.isError ? (
          <ErrorState error={sources.error} onRetry={() => void sources.refetch()} />
        ) : (
          <Table>
            <THead>
              <Th>{t('common.name')}</Th>
              <Th>{t('sources.kind')}</Th>
              <Th>{t('sources.config')}</Th>
              <Th>{t('sources.status')}</Th>
              <Th align="center">{t('common.enabled')}</Th>
              <Th align="right">{t('common.actions')}</Th>
            </THead>
            <TBody>
              {sources.data.items.length === 0 ? (
                <EmptyRow colSpan={6} message={<span className="inline-flex flex-col items-center gap-1"><Camera className="size-5" />{t('sources.empty')}</span>} />
              ) : (
                sources.data.items.map((s) => (
                  <Tr key={s.id}>
                    <Td className="font-medium">{s.name} <span className="text-xs text-muted">#{s.id}</span></Td>
                    <Td><Badge tone="info">{kindList.find((k) => k.kind === s.kind)?.label ?? s.kind}</Badge></Td>
                    <Td><code className="block max-w-xs truncate font-mono text-xs text-muted" title={JSON.stringify(s.config)}>{JSON.stringify(s.config)}</code></Td>
                    <Td><code className="block max-w-xs truncate font-mono text-xs text-muted" title={JSON.stringify(s.status)}>{JSON.stringify(s.status)}</code></Td>
                    <Td align="center"><Switch checked={s.is_enabled} onChange={(v) => patch.mutate({ id: s.id, is_enabled: v })} /></Td>
                    <Td align="right">
                      <span className="inline-flex gap-1">
                        {s.kind === 'upload' ? (
                          <label className="btn-icon cursor-pointer" title={t('common.upload')}>
                            <Upload size={15} />
                            <input type="file" accept="image/*" className="hidden" onChange={(e) => void onPush(s, e.target.files?.[0])} />
                          </label>
                        ) : null}
                        <IconButton label={t('sources.preview')} onClick={() => setPreview({ source: s, url: sourcePreviewUrl(s.id) })}><Eye size={15} /></IconButton>
                        <IconButton label={t('common.edit')} onClick={() => setEditing({ id: s.id, body: { name: s.name, kind: s.kind, config: { ...s.config }, is_enabled: s.is_enabled } })}><Pencil size={15} /></IconButton>
                        <IconButton label={t('common.delete')} onClick={() => setPendingDelete(s)}><Trash2 size={15} className="text-critical" /></IconButton>
                      </span>
                    </Td>
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
            <Select label={t('sources.kind')} value={body.kind} onChange={(e) => setEditing({ ...editing!, body: { ...body, kind: e.target.value, config: defaultsFor(e.target.value) } })} options={kindList.map((k) => ({ value: k.kind, label: k.label }))} />
            {(fieldsFor.get(body.kind) ?? []).map((field) => (
              <ConfigField key={field} kind={body.kind} field={field} value={body.config[field]} onChange={(v) => setEditing({ ...editing!, body: { ...body, config: { ...body.config, [field]: v } } })} />
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

      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void onDelete()} title={t('sources.deleteTitle')} message={t('sources.deleteMessage', { name: pendingDelete?.name ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </Page>
  )
}
