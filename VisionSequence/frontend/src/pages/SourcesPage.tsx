/** 影像來源 CRUD。config 欄位依 kind 的 fields 顯示（伺服器 /sources/kinds 給）。 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Camera, FolderOpen, LayoutGrid, ListTree, Plus, RefreshCw } from 'lucide-react'
import { Page } from '@/components/layout/AppShell'
import { SourceCards, SourceTree } from '@/components/sources/SourceViews'
import { Badge, Button, Card, Checkbox, ConfirmDialog, EmptyState, ErrorState, GROUP_ALL, GroupChips, GroupSelect, LoadingState, Modal, PageHeader, SegmentedControl, Select, TextInput, matchGroup } from '@/components/ui'
import { GroupManager } from '@/components/GroupManager'
import { CaptureDownloadButton } from '@/components/capture/CaptureSection'
import { api, sourcePreviewUrl } from '@/lib/api'
import { FsBrowser } from '@/components/FsBrowser'
import { errorMessage } from '@/lib/errors'
import { sourceStatus } from '@/lib/sources'
import { useCaptureClients, useGroups, useSourceKinds, useSourceMutations, useSources, type SourceBody } from '@/lib/queries'
import type { CaptureClient, ImageSource } from '@/lib/types'
import { useToast } from '@/providers/ToastProvider'
/** 每個 config 欄位的輸入型態。 */
const FIELD_TYPE: Record<string, 'text' | 'number' | 'boolean' | 'select'> = {
  path: 'text',
  loop: 'boolean',
  sort: 'select',
  pattern: 'text',
  width: 'number',
  height: 'number',
  seed: 'number',
  defect_rate: 'number',
  class: 'text',
  timeout_ms: 'number',
  fresh: 'boolean',
}
const FIELD_DEFAULT: Record<string, unknown> = { loop: true, sort: 'name', pattern: '*.png;*.jpg;*.bmp', width: 1280, height: 960, seed: 0, defect_rate: 0.3, mode: 'on_demand', timeout_ms: 1000, fresh: true, encoding: 'auto' }
const VIEW_KEY = 'vs.sourcesView'
type SourceView = 'tree' | 'cards'

//: 預設樹狀：來源多起來（多台相機＋資料夾）時，依種類分層比一長串清單好找
function storedView(): SourceView {
  try {
    return localStorage.getItem(VIEW_KEY) === 'cards' ? 'cards' : 'tree'
  } catch {
    return 'tree'
  }
}

const CAPTURE_MODES = ['on_demand', 'stream'] as const
const CAPTURE_ENCODINGS = ['auto', 'raw', 'lz4', 'jpeg'] as const
function ConfigField({ kind, field, value, config, onChange, onBrowse, captureClients, captureLoading, onRefreshCapture }: {
  kind: string
  field: string
  value: unknown
  config?: Record<string, unknown>
  onChange: (v: unknown) => void
  onBrowse?: (mode: 'dir' | 'file') => void
  captureClients?: CaptureClient[] | null
  captureLoading?: boolean
  onRefreshCapture?: () => void
}) {
  const { t } = useTranslation()
  const label = t(`sources.fields.${field}`, { defaultValue: field })
  const type = FIELD_TYPE[field] ?? 'text'
  // 擷取端相機：擷取端／通道由 /capture/clients 即時列出（表單開著才輪詢）；離線的舊值保留顯示
  if (kind === 'capture' && field === 'client') {
    const list = captureClients ?? []
    const current = String(value ?? '')
    const options = [{ value: '', label: t('sources.capturePickClient') }, ...list.map((c) => ({ value: c.name, label: `${c.name} (${c.hostname}${c.local ? `・${t('sources.captureLocal')}` : ''})` }))]
    if (current && !list.some((c) => c.name === current)) options.push({ value: current, label: t('sources.captureClientOffline', { name: current }) })
    return (
      <div className="space-y-1.5">
        <div className="flex items-end gap-2">
          <Select label={label} value={current} onChange={(e) => onChange(e.target.value)} options={options} data-testid="cfg-capture-client" />
          <Button loading={captureLoading} onClick={onRefreshCapture} title={t('sources.captureRefresh')} data-testid="cfg-capture-refresh"><RefreshCw size={14} /> {t('common.refresh')}</Button>
        </div>
        {captureClients && !list.length ? (
          <div className="flex flex-wrap items-center gap-2 text-xs text-subtle">
            <span>{t('sources.captureNoClients')}</span>
            <CaptureDownloadButton size="xs" />
          </div>
        ) : (
          <p className="text-xs text-subtle">{t('sources.captureHint')}</p>
        )}
      </div>
    )
  }
  if (kind === 'capture' && field === 'channel') {
    const client = (captureClients ?? []).find((c) => c.name === String(config?.client ?? ''))
    const channels = (client?.channels ?? []).filter((c) => c.enabled)
    const current = String(value ?? '')
    const options = [{ value: '', label: t('sources.capturePickChannel') }, ...channels.map((c) => ({ value: c.id, label: `${c.label} · ${c.width}×${c.height} ${c.pixel_format}${c.in_use_by.length ? ` · ${t('sources.inUseBy', { name: c.in_use_by.join(', ') })}` : ''}` }))]
    if (current && !channels.some((c) => c.id === current)) options.push({ value: current, label: current })
    return (
      <div className="space-y-1.5">
        <Select label={label} value={current} onChange={(e) => onChange(e.target.value)} options={options} data-testid="cfg-capture-channel" />
        {client && !channels.length ? <p className="text-xs text-subtle">{t('sources.captureNoChannels')}</p> : null}
      </div>
    )
  }
  if (kind === 'capture' && field === 'mode') {
    return <Select label={label} value={String(value ?? 'on_demand')} onChange={(e) => onChange(e.target.value)} options={CAPTURE_MODES.map((m) => ({ value: m, label: t(`sources.captureModes.${m}`) }))} />
  }
  if (kind === 'capture' && field === 'encoding') {
    return <Select label={label} value={String(value ?? 'auto')} onChange={(e) => onChange(e.target.value)} options={CAPTURE_ENCODINGS.map((m) => ({ value: m, label: t(`sources.captureEncodings.${m}`) }))} />
  }
  if (kind === 'capture' && field === 'timeout_ms') {
    return (
      <div className="space-y-1">
        <TextInput label={label} type="number" step={100} value={value === undefined || value === null ? '' : String(value)} onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />
        <p className="text-xs text-subtle">{t('sources.captureTimeoutHint')}</p>
      </div>
    )
  }
  if (kind === 'capture' && field === 'fresh') {
    return (
      <div className="space-y-1">
        <Checkbox label={label} checked={value === undefined || value === null ? true : Boolean(value)} onChange={onChange} />
        <p className="text-xs text-subtle">{t('sources.captureFreshHint')}</p>
      </div>
    )
  }
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
/** 狀態欄：徽章（已開啟／未開啟／錯誤）＋張數，完整 JSON 留在 title。 */
function SourceStatusCell({ status }: { status: Record<string, unknown> | null | undefined }) {
  const { t } = useTranslation()
  const view = sourceStatus(status)
  return (
    <span className="inline-flex max-w-xs items-center gap-1.5" title={JSON.stringify(status ?? {})}>
      <Badge tone={view.tone}>{t(`sources.${view.key}`)}</Badge>
      {view.frames !== null ? <span className="tnum text-xs text-muted">{t('sources.statusFrames', { count: view.frames })}</span> : null}
      {view.fps !== null ? <span className="tnum whitespace-nowrap text-xs text-muted">{t('sources.statusFps', { fps: view.fps })}</span> : null}
      {view.ageMs !== null ? <span className="tnum whitespace-nowrap text-xs text-muted">{t('sources.statusAge', { ms: view.ageMs })}</span> : null}
      {view.shm ? <Badge className="whitespace-nowrap">{t('sources.captureLocal')}</Badge> : null}
      {view.error ? <span className="truncate text-xs text-critical">{view.error}</span> : null}
    </span>
  )
}
export function SourcesPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const sources = useSources(true)
  const kinds = useSourceKinds()
  const { create, patch, remove, push } = useSourceMutations()
  const [editing, setEditing] = useState<{ id: number | null; body: SourceBody } | null>(null)
  const [groupFilter, setGroupFilter] = useState(GROUP_ALL)
  const [view, setView] = useState<SourceView>(storedView)
  const [managingGroups, setManagingGroups] = useState(false)
  const groups = useGroups('source')
  const [pendingDelete, setPendingDelete] = useState<ImageSource | null>(null)
  const [preview, setPreview] = useState<{ source: ImageSource; url: string } | null>(null)
  const [browsing, setBrowsing] = useState<'dir' | 'file' | null>(null)
  // 擷取端清單只在「擷取端相機」表單開著時輪詢
  const capture = useCaptureClients(editing !== null && editing.body.kind === 'capture')
  const kindList = kinds.data ?? []
  const visible = (sources.data?.items ?? []).filter((s) => matchGroup(s, groupFilter))
  //: 兩種檢視共用的資料與動作（樹狀與卡片只是排版不同）
  const viewHandlers = {
    kindLabel: (kind: string) => kindList.find((k) => k.kind === kind)?.label ?? kind,
    status: (s: ImageSource) => <SourceStatusCell status={s.status} />,
    onPreview: (s: ImageSource) => setPreview({ source: s, url: sourcePreviewUrl(s.id) }),
    onEdit: (s: ImageSource) => setEditing({ id: s.id, body: { name: s.name, kind: s.kind, config: { ...s.config }, is_enabled: s.is_enabled, group: s.group } }),
    onDelete: (s: ImageSource) => setPendingDelete(s),
    onToggle: (s: ImageSource, enabled: boolean) => patch.mutate({ id: s.id, is_enabled: enabled }),
    onPush: (s: ImageSource, file: File | undefined) => void onPush(s, file),
  }
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
  // 儲存前測試擷取：依表單目前的 kind／config 抓一張，顯示尺寸、耗時與縮圖；換類型或重開表單即清除
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ ok: boolean; width?: number; height?: number; ms?: number; image?: string; error?: string } | null>(null)
  useEffect(() => { setTestResult(null) }, [editing?.id, editing?.body.kind])
  async function testGrab() {
    if (!body) return
    setTesting(true)
    try {
      const r = await api.post<{ width: number; height: number; ms: number; image: string }>('/vision/sources/test', { kind: body.kind, config: body.config })
      setTestResult({ ok: true, ...r })
    } catch (error) {
      setTestResult({ ok: false, error: errorMessage(error) })
    } finally {
      setTesting(false)
    }
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
      <PageHeader title={t('sources.title')} description={t('sources.subtitle')} actions={<><SegmentedControl
          value={view}
          onChange={(v) => { setView(v); try { localStorage.setItem(VIEW_KEY, v) } catch { /* 忽略 */ } }}
          options={[
            { value: 'tree', label: <span className="flex items-center gap-1"><ListTree size={13} /> {t('assets.views.tree')}</span> },
            { value: 'cards', label: <span className="flex items-center gap-1"><LayoutGrid size={13} /> {t('assets.views.cards')}</span> },
          ]}
        /><CaptureDownloadButton /><Button onClick={() => setManagingGroups(true)} data-testid="manage-groups">{t('groups.manage')}</Button><Button variant="primary" icon={<Plus size={15} />} onClick={openCreate}>{t('sources.create')}</Button></>} />
      <GroupChips items={sources.data?.items ?? []} value={groupFilter} onChange={setGroupFilter} />
      {sources.isPending ? (
        <Card><LoadingState /></Card>
      ) : sources.isError ? (
        <Card><ErrorState error={sources.error} onRetry={() => void sources.refetch()} /></Card>
      ) : visible.length === 0 ? (
        <Card><EmptyState icon={<Camera className="size-6" />} title={t('sources.empty')} /></Card>
      ) : view === 'tree' ? (
        <SourceTree items={visible} {...viewHandlers} />
      ) : (
        <SourceCards items={visible} {...viewHandlers} />
      )}
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
              <ConfigField key={field} kind={body.kind} field={field} value={body.config[field]} config={body.config}
                onChange={(v) => setEditing({ ...editing!, body: { ...body, config: field === 'client' ? { ...body.config, client: v, channel: '' } : { ...body.config, [field]: v } } })}
                onBrowse={(mode) => setBrowsing(mode)}
                captureClients={capture.data?.items ?? null} captureLoading={capture.isFetching} onRefreshCapture={() => void capture.refetch()} />
            ))}
            <div className="space-y-2 rounded-md border border-line bg-surface p-2" data-testid="source-test-box">
              <div className="flex flex-wrap items-center gap-2">
                <Button loading={testing} disabled={body.kind === 'upload'} onClick={() => void testGrab()} data-testid="source-test">{t('sources.test')}</Button>
                <span className={`text-xs ${testResult && !testResult.ok ? 'text-critical' : 'text-muted'}`} data-testid="source-test-status">
                  {body.kind === 'upload'
                    ? t('sources.testUpload')
                    : testResult
                      ? (testResult.ok ? t('sources.testOk', { w: testResult.width, h: testResult.height, ms: testResult.ms }) : t('sources.testFail', { error: testResult.error }))
                      : t('sources.testHint')}
                </span>
              </div>
              {testResult?.ok && testResult.image ? <img src={testResult.image} alt="" className="max-h-44 rounded border border-line" data-testid="source-test-image" /> : null}
            </div>
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
