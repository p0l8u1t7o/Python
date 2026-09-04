/** 流程列表：新增、複製、刪除、啟用切換、進入編輯器。 */
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { BarChart3, BookOpen, Copy, Download, Gem, LayoutTemplate, Lock, Pencil, Plus, SlidersHorizontal, Trash2, Upload, Users, Workflow } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { BoundBadge, BoundRecipeSelect } from '@/components/recipes/BoundRecipeSelect'
import { RecipeDrawer } from '@/components/recipes/RecipeDrawer'
import { TemplateGallery } from '@/components/templates/TemplateGallery'
import { Badge, Button, Card, ConfirmDialog, EmptyRow, ErrorState, IconButton, LoadingState, Modal, PageHeader, Select, StatusBadge, Switch, TBody, THead, Table, Td, TextArea, TextInput, Th, Tr } from '@/components/ui'
import { downloadFile } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { useFlowMutations, useFlows, useImportFlow, useRecipes, useSources } from '@/lib/queries'
import { formatDateTime, formatDateTimeFull } from '@/lib/format'
import type { Flow } from '@/lib/types'
import { useAuth } from '@/providers/AuthProvider'
import { useToast } from '@/providers/ToastProvider'

/** 列上的綁定配方：有配方才抓清單；「配方」鈕開側滑面板。 */
function RecipeCell({ flow, readOnly, onOpen }: { flow: Flow; readOnly: boolean; onOpen: () => void }) {
  const { t } = useTranslation()
  const recipes = useRecipes(flow.recipe_count ? flow.id : null)
  const list = recipes.data?.items ?? []
  return (
    <span className="flex items-center gap-1.5" onClick={(e) => e.stopPropagation()}>
      {flow.recipe_count ? <BoundRecipeSelect flowId={flow.id} recipes={list} disabled={readOnly} showLabel={false} testId={`row-bound-${flow.id}`} /> : <span className="text-xs text-muted">—</span>}
      <Button size="xs" icon={<BookOpen size={13} />} onClick={onOpen} title={t('recipes.manage')} data-testid="row-recipes">{t('recipes.drawerTitle')}{flow.recipe_count ? ` (${flow.recipe_count})` : ''}</Button>
    </span>
  )
}

/** 列名稱旁的「綁定：partA」（有配方時）。 */
function RowBound({ flow }: { flow: Flow }) {
  const recipes = useRecipes(flow.recipe_count ? flow.id : null)
  if (!flow.recipe_count) return null
  return <BoundBadge recipes={recipes.data?.items} className="font-normal" />
}

export function FlowsPage() {
  const { t } = useTranslation()
  const toast = useToast()
  const navigate = useNavigate()
  const auth = useAuth()
  const [q, setQ] = useState('')
  const [mine, setMine] = useState(false)
  const flows = useFlows(q, mine)
  const myId = auth.me?.user?.id ?? null
  /** 共用流程（或別人的）一般使用者只能看、複製，不能改 */
  const readOnly = (_flow: Flow) => !auth.isEngineer
  const { create, patch, remove, duplicate } = useFlowMutations()
  const [creating, setCreating] = useState(false)
  const [gallery, setGallery] = useState(false)
  const [form, setForm] = useState({ name: '', description: '' })
  const [pendingDelete, setPendingDelete] = useState<Flow | null>(null)
  const importFlow = useImportFlow()
  const sources = useSources()
  const [importing, setImporting] = useState(false)
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importSource, setImportSource] = useState('')
  const importInput = useRef<HTMLInputElement>(null)
  const [recipeFlow, setRecipeFlow] = useState<Flow | null>(null)

  async function onExport(flow: Flow) {
    try {
      await downloadFile(`/vision/flows/${flow.id}/export`, `${flow.name}.flow.json`)
      toast.success(t('flows.exported', { name: flow.name }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function onImport() {
    if (!importFile) return toast.error(t('flows.importNoFile'))
    try {
      const res = await importFlow.mutateAsync({ file: importFile, source_id: importSource ? Number(importSource) : null })
      toast.success(res.created ? t('flows.imported', { name: res.flow.name }) : t('flows.importedUpdated', { name: res.flow.name }))
      setImporting(false)
      setImportFile(null)
      navigate(`/flows/${res.flow.id}`)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function onCreate() {
    if (!form.name.trim()) return toast.error(t('flows.nameRequired'))
    try {
      const flow = await create.mutateAsync({ name: form.name.trim(), description: form.description })
      setCreating(false)
      setForm({ name: '', description: '' })
      toast.success(t('flows.created'))
      navigate(`/flows/${flow.id}`)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function onFromTemplate({ graph, name, description, missingSource }: { graph: Flow['graph']; name: string; description: string; missingSource: boolean }) {
    const flow = await create.mutateAsync({ name, description, graph })
    setGallery(false)
    toast.success(t('flows.created'))
    if (missingSource) toast.warning(t('templates.missingSource'))
    navigate(`/flows/${flow.id}`)
  }

  async function onDuplicate(flow: Flow) {
    try {
      await duplicate.mutateAsync(flow.id)
      toast.success(t('flows.duplicated'))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  async function onDelete() {
    if (!pendingDelete) return
    try {
      await remove.mutateAsync(pendingDelete.id)
      toast.success(t('flows.deleted'))
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setPendingDelete(null)
    }
  }

  return (
    <Page>
      <PageHeader
        title={t('flows.title')}
        description={t('flows.subtitle')}
        actions={
          <>
            <input className="input w-48" placeholder={`${t('common.search')}…`} value={q} onChange={(e) => setQ(e.target.value)} />
            <label className="flex items-center gap-1.5 text-xs text-muted" title={t('flows.mineHint')}>
              <Switch checked={mine} label={t('flows.mine')} onChange={setMine} />
              {t('flows.mine')}
            </label>
            <Button icon={<LayoutTemplate size={15} />} onClick={() => setGallery(true)} data-testid="btn-from-template">
              {t('templates.fromTemplate')}
            </Button>
            <Button icon={<Upload size={15} />} onClick={() => setImporting(true)} title={t('flows.importHint')} data-testid="btn-import">
              {t('flows.import')}
            </Button>
            <Button variant="primary" icon={<Plus size={15} />} onClick={() => setCreating(true)}>
              {t('flows.create')}
            </Button>
          </>
        }
      />
      <Card className="overflow-hidden">
        {flows.isPending ? (
          <LoadingState />
        ) : flows.isError ? (
          <ErrorState error={flows.error} onRetry={() => void flows.refetch()} />
        ) : (
          <Table>
            <THead>
              <Th>{t('common.name')}</Th>
              <Th className="max-xl:hidden">{t('flows.owner')}</Th>
              <Th align="center">{t('common.enabled')}</Th>
              <Th align="right" className="max-xl:hidden">{t('flows.nodes')}</Th>
              <Th align="right" className="max-lg:hidden">{t('flows.version')}</Th>
              <Th className="max-sm:hidden">{t('flows.stats')}</Th>
              <Th className="max-xl:hidden">{t('recipes.bound')}</Th>
              <Th className="max-xl:hidden">{t('flows.updated')}</Th>
              <Th align="right">{t('common.actions')}</Th>
            </THead>
            <TBody>
              {flows.data.items.length === 0 ? (
                <EmptyRow colSpan={9} message={<span className="inline-flex flex-col items-center gap-1"><Workflow className="size-5" />{t('flows.empty')}<span className="text-xs">{t('flows.emptyHint')}</span></span>} />
              ) : (
                flows.data.items.map((flow) => (
                  <Tr key={flow.id} onClick={() => navigate(`/flows/${flow.id}`)}>
                    <Td className="sm:min-w-52">
                      {/* min-w：名稱旁有「未教導」「綁定：…」標籤時，表格自動配寬會把名稱擠成一字一行 */}
                      <p className="flex flex-wrap items-center gap-1.5 font-medium">
                        {readOnly(flow) ? <Lock size={13} className="shrink-0 text-muted" aria-label={t('flows.readOnly')} /> : null}
                        <span className="min-w-0 break-words">{flow.name}</span>
                        {flow.commissioned === false ? <span title={t('flows.notCommissionedHint')}><Badge tone="warning" className="font-normal">{t('flows.notCommissioned')}</Badge></span> : null}
                        <RowBound flow={flow} />
                      </p>
                      {flow.description ? <p className="line-clamp-2 text-xs leading-snug text-muted" title={flow.description}>{flow.description}</p> : null}
                    </Td>
                    <Td className="max-xl:hidden">
                      {flow.owner_id === null ? (
                        <span className="inline-flex items-center gap-1 text-xs text-muted" title={readOnly(flow) ? t('flows.readOnly') : undefined}><Users size={12} /> {t('flows.shared')}</span>
                      ) : (
                        <span className="text-xs">{flow.owner_name}{flow.owner_id === myId ? <span className="ml-1 text-muted">({t('users.you')})</span> : null}</span>
                      )}
                    </Td>
                    <Td align="center">
                      <span onClick={(e) => e.stopPropagation()} title={readOnly(flow) ? t('flows.readOnly') : undefined}>
                        <Switch checked={flow.is_enabled} disabled={readOnly(flow)} label={t('flows.enabledToggle')} onChange={(v) => patch.mutate({ id: flow.id, is_enabled: v }, { onError: (error) => toast.error(errorMessage(error)) })} />
                      </span>
                    </Td>
                    <Td align="right" className="tnum max-xl:hidden">{flow.node_count}</Td>
                    <Td align="right" className="tnum max-lg:hidden">v{flow.version}</Td>
                    <Td className="max-sm:hidden">
                      <div className="flex items-center gap-2">
                        <StatusBadge status={flow.stats.last_status || null} />
                        <span className="tnum whitespace-nowrap text-xs text-muted">{flow.stats.runs} 次 · {Math.round(flow.stats.avg_ms)} ms</span>
                        {flow.continuous ? <Badge tone="brand">{t('dashboard.continuous')}</Badge> : null}
                      </div>
                    </Td>
                    <Td className="max-xl:hidden"><RecipeCell flow={flow} readOnly={readOnly(flow)} onOpen={() => setRecipeFlow(flow)} /></Td>
                    <Td className="tnum max-xl:hidden whitespace-nowrap text-xs text-muted"><span title={formatDateTimeFull(flow.updated_at)}>{formatDateTime(flow.updated_at)}</span></Td>
                    <Td align="right">
                      <span className="inline-flex min-w-24 max-w-28 flex-wrap justify-end gap-0.5 sm:min-w-0 sm:max-w-none sm:flex-nowrap sm:gap-1" onClick={(e) => e.stopPropagation()}>
                        <Link to={`/flows/${flow.id}`} aria-label={t('flows.open')} title={t('flows.open')}><IconButton label={t('flows.open')}><Pencil size={15} /></IconButton></Link>
                        <Link to={`/flows/${flow.id}/teach`} aria-label={t('flows.teach')} title={t('flows.teach')}><IconButton label={t('flows.teach')} data-testid="row-teach"><SlidersHorizontal size={15} /></IconButton></Link>
                        <Link to={`/flows/${flow.id}/golden`} aria-label={t('flows.golden')} title={t('flows.golden')}><IconButton label={t('flows.golden')} data-testid="row-golden"><Gem size={15} /></IconButton></Link>
                        <Link to={`/flows/${flow.id}/stats`} aria-label={t('stats.open')} title={t('stats.open')}><IconButton label={t('stats.open')}><BarChart3 size={15} /></IconButton></Link>
                        <IconButton label={t('flows.export')} title={t('flows.exportHint')} onClick={() => void onExport(flow)} data-testid="row-export"><Download size={15} /></IconButton>
                        <IconButton label={t('common.duplicate')} onClick={() => void onDuplicate(flow)}><Copy size={15} /></IconButton>
                        <span className="mx-0.5 hidden h-4 w-px bg-line sm:inline-block" aria-hidden />
                        <IconButton label={readOnly(flow) ? t('flows.readOnly') : t('common.delete')} disabled={readOnly(flow)} onClick={() => setPendingDelete(flow)} className="hover:!bg-critical-soft hover:!text-critical"><Trash2 size={15} /></IconButton>
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
        open={creating}
        onClose={() => setCreating(false)}
        title={t('flows.createTitle')}
        dirty={Boolean(form.name || form.description)}
        footer={
          <>
            <Button onClick={() => setCreating(false)}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={create.isPending} onClick={() => void onCreate()}>{t('common.create')}</Button>
          </>
        }
      >
        <div className="space-y-3">
          <TextInput label={t('common.name')} required autoFocus value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} onKeyDown={(e) => e.key === 'Enter' && void onCreate()} />
          <TextArea label={t('common.description')} rows={2} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
        </div>
      </Modal>

      <Modal
        open={importing}
        onClose={() => setImporting(false)}
        title={t('flows.importTitle')}
        description={t('flows.importHint')}
        footer={
          <>
            <Button onClick={() => setImporting(false)}>{t('common.cancel')}</Button>
            <Button variant="primary" icon={<Upload size={14} />} loading={importFlow.isPending} onClick={() => void onImport()} data-testid="import-confirm">{t('flows.import')}</Button>
          </>
        }
      >
        <div className="space-y-3">
          <div>
            <span className="label">{t('flows.importFile')}</span>
            <div className="flex items-center gap-2">
              <Button size="sm" onClick={() => importInput.current?.click()}>{t('flows.importFile')}</Button>
              <input ref={importInput} type="file" accept=".json,application/json" className="hidden" data-testid="import-input" onChange={(e) => setImportFile(e.target.files?.[0] ?? null)} />
              <span className="text-xs text-muted">{importFile?.name ?? '—'}</span>
            </div>
          </div>
          <Select label={t('flows.importSource')} value={importSource} placeholder={t('flows.importSourceNone')} onChange={(e) => setImportSource(e.target.value)} options={(sources.data?.items ?? []).map((src) => ({ value: String(src.id), label: `${src.name}（${src.kind}）` }))} data-testid="import-source" />
        </div>
      </Modal>

      <RecipeDrawer open={recipeFlow !== null} onClose={() => setRecipeFlow(null)} flowId={recipeFlow?.id ?? 0} readOnly={recipeFlow ? readOnly(recipeFlow) : true} />
      <TemplateGallery open={gallery} onClose={() => setGallery(false)} mode="create" onPick={onFromTemplate} />
      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void onDelete()} title={t('flows.deleteTitle')} message={t('flows.deleteMessage', { name: pendingDelete?.name ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </Page>
  )
}
