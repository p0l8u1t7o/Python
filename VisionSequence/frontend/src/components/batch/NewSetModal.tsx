/** 新增影像集：上傳多張影像，或從影像來源擷取 N 張。 */
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { FolderOpen } from 'lucide-react'

import { Button, Modal, SegmentedControl, Select, TextInput } from '@/components/ui'
import { useBatchMutations, type BatchSet } from '@/lib/batch'
import { errorMessage } from '@/lib/errors'
import { useSources } from '@/lib/queries'
import { useToast } from '@/providers/ToastProvider'

export function NewSetModal({ open, onClose, flowId, maxImages, onCreated }: { open: boolean; onClose: () => void; flowId: number; maxImages: number; onCreated: (set: BatchSet) => void }) {
  const { t } = useTranslation()
  const toast = useToast()
  const sources = useSources()
  const { createUpload, createFromSource } = useBatchMutations(flowId)
  const fileInput = useRef<HTMLInputElement>(null)
  const [mode, setMode] = useState<'upload' | 'source'>('upload')
  const [files, setFiles] = useState<File[]>([])
  const [name, setName] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [count, setCount] = useState('10')
  const [dragging, setDragging] = useState(false)
  const busy = createUpload.isPending || createFromSource.isPending

  function addFiles(list: FileList | File[] | null) {
    if (!list) return
    const incoming = [...list].filter((f) => f.type.startsWith('image/') || /\.(png|jpe?g|bmp|tiff?|webp)$/i.test(f.name))
    const merged = [...files, ...incoming]
    if (merged.length > maxImages) toast.warning(t('batchPage.maxImages', { count: maxImages }))
    setFiles(merged.slice(0, maxImages))
  }

  async function create() {
    try {
      const set = mode === 'upload'
        ? await createUpload.mutateAsync({ files, name: name.trim() || undefined })
        : await createFromSource.mutateAsync({ source_id: Number(sourceId), count: Math.max(1, Math.min(maxImages, Number(count) || 1)), name: name.trim() || undefined })
      toast.success(t('batchPage.created', { name: set.name }))
      setFiles([])
      setName('')
      onCreated(set)
      onClose()
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  const canCreate = mode === 'upload' ? files.length > 0 : Boolean(sourceId)
  return (
    <Modal open={open} onClose={onClose} title={t('batchPage.newSet')} description={t('batchPage.maxImages', { count: maxImages })}
      footer={<><Button onClick={onClose}>{t('common.cancel')}</Button><Button variant="primary" loading={busy} disabled={!canCreate} onClick={() => void create()} data-testid="batch-set-create">{t('batchPage.create')}</Button></>}>
      <div className="space-y-3">
        <SegmentedControl size="sm" value={mode} onChange={setMode} options={[{ value: 'upload', label: t('batchPage.upload') }, { value: 'source', label: t('batchPage.fromSource') }]} />
        <TextInput label={t('batchPage.setName')} value={name} onChange={(e) => setName(e.target.value)} placeholder={t('batchPage.setNamePlaceholder')} data-testid="batch-set-name" />
        {mode === 'upload' ? (
          <div className={`flex flex-col gap-2 rounded-lg border border-dashed p-3 ${dragging ? 'border-brand bg-brand-soft/40' : 'border-line'}`}
            onDragOver={(e) => { e.preventDefault(); setDragging(true) }} onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); addFiles(e.dataTransfer.files) }} data-testid="batch-drop">
            <div className="flex flex-wrap items-center gap-2">
              <Button size="sm" icon={<FolderOpen size={14} />} onClick={() => fileInput.current?.click()}>{t('batchPage.pickFiles')}</Button>
              <input ref={fileInput} type="file" accept="image/*" multiple className="hidden" data-testid="batch-set-input" onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
              <span className="text-xs text-muted">{files.length ? t('batchPage.images', { count: files.length }) : t('batchPage.dropHint')}</span>
              {files.length ? <button type="button" className="text-xs text-muted hover:underline" onClick={() => setFiles([])}>{t('common.clear')}</button> : null}
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-end gap-2">
            <Select label={t('batchPage.source')} value={sourceId} onChange={(e) => setSourceId(e.target.value)} placeholder="—" options={(sources.data?.items ?? []).map((s) => ({ value: String(s.id), label: s.name }))} data-testid="batch-set-source" />
            <TextInput label={t('batchPage.count')} type="number" min={1} max={maxImages} className="!w-24" value={count} onChange={(e) => setCount(e.target.value)} />
          </div>
        )}
      </div>
    </Modal>
  )
}
