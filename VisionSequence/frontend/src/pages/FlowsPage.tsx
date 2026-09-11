/** 流程列表：建立檢測任務／建立進階流程、每列 檢測任務／開啟畫布／更多（參數卡、Golden Set、統計、匯出、複製、刪除）、啟用切換；點整列進檢測任務頁。 */
import { useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { BarChart3, BookOpen, Copy, Download, Gem, LayoutTemplate, ListChecks, Lock, MoreHorizontal, Pencil, Plus, SlidersHorizontal, Trash2, Upload, Users, Workflow } from 'lucide-react'

import { Page } from '@/components/layout/AppShell'
import { BoundBadge, BoundRecipeSelect } from '@/components/recipes/BoundRecipeSelect'
import { RecipeDrawer } from '@/components/recipes/RecipeDrawer'
import { TemplateGallery } from '@/components/templates/TemplateGallery'
import { ActionMenu, ActionMenuItem, ActionMenuSeparator, Badge, Button, Card, ConfirmDialog, EmptyRow, ErrorState, IconButton, LoadingState, Modal, PageHeader, Select, StatusBadge, Switch, TBody, THead, Table, Td, TextArea, TextInput, Th, Tr } from '@/components/ui'
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
  /** 建立入口分兩種（Suggest5 第 6 點）：檢測任務（建好進任務頁）與進階流程（建好進畫布） */
  const [creating, setCreating] = useState<'inspect' | 'advanced' | null>(null)
  const [gallery, setGallery] = useState(false)
  const [form, setForm] = useState({ name: '', description: '' })
  const [nameError, setNameError] = useState<string | null>(null)
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
    if (!form.name.trim()) {
      // 欄位問題留在欄位旁並聚焦第一個錯誤欄位；toast 只給整體操作結果（Suggest5 第 7 點）
      setNameError(t('flows.nameRequired'))
      setTimeout(() => document.querySelector<HTMLElement>('[role="dialog"] [aria-invalid="true"]')?.focus(), 0)
      return
    }
    try {
      const mode = creating
      const flow = await create.mutateAsync({ name: form.name.trim(), description: form.description })
      setCreating(null)
      setForm({ name: '', description: '' })
      toast.success(t('flows.created'))
      navigate(mode === 'advanced' ? `/flows/${flow.id}` : `/flows/${flow.id}/inspect`)
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
            <Button icon={<Plus size={15} />} onClick={() => setCreating('advanced')} title={t('flows.createAdvancedHint')} data-testid="btn-create-advanced">
              {t('flows.createAdvanced')}
            </Button>
            <Button variant="primary" icon={<ListChecks size={15} />} onClick={() => setCreating('inspect')} title={t('flows.createInspectionHint')} data-testid="btn-create-inspection">
              {t('flows.createInspection')}
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
                  <Tr key={flow.id} onClick={() => navigate(`/flows/${flow.id}/inspect`)}>
                    <Td className="sm:min-w-52">
                      {/* min-w：名稱旁有「未教導」「綁定：…」標籤時，表格自動配寬會把名稱擠成一字一行 */}
                      <p className="flex flex-wrap items-center gap-1.5 font-medium">
                        {readOnly(flow) ? <Lock size={13} className="shrink-0 text-muted" aria-label={t('flows.readOnly')} /> : null}
                        <span className="min-w-0 break-words">{flow.name}</span>
                        {flow.check_count === 0 && flow.is_enabled ? <span title={t('flows.noChecksHint')} data-testid="row-no-checks"><Badge tone="critical" className="font-normal">{t('flows.noChecks')}</Badge></span> : null}
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
                        <span className="tnum whitespace-nowrap text-xs text-muted">{t('flows.runCount', { count: flow.stats.runs })} · {Math.round(flow.stats.avg_ms)} ms</span>
                        {flow.continuous ? <Badge tone="brand">{t('dashboard.continuous')}</Badge> : null}
                      </div>
                    </Td>
                    <Td className="max-xl:hidden"><RecipeCell flow={flow} readOnly={readOnly(flow)} onOpen={() => setRecipeFlow(flow)} /></Td>
                    <Td className="tnum max-xl:hidden whitespace-nowrap text-xs text-muted"><span title={formatDateTimeFull(flow.updated_at)}>{formatDateTime(flow.updated_at)}</span></Td>
                    <Td align="right">
                      {/* 每列只留 檢測任務／開啟畫布／更多（Suggest5 第 5 點）；其餘動作收進選單 */}
                      <span className="inline-flex items-center justify-end gap-1 whitespace-nowrap" onClick={(e) => e.stopPropagation()}>
                        <Link to={`/flows/${flow.id}/inspect`} className="btn-secondary !h-8 whitespace-nowrap !px-2 !text-xs" data-testid="row-inspect">{t('inspect.title')}</Link>
                        <Link to={`/flows/${flow.id}`} aria-label={t('flows.open')} title={t('flows.open')} data-testid="row-open"><IconButton label={t('flows.open')}><Pencil size={15} /></IconButton></Link>
                        <ActionMenu testId={`row-more-${flow.id}`} label={t('common.more')} trigger={(open, props) => <IconButton label={t('common.more')} active={open} data-testid="row-more" {...props}><MoreHorizontal size={15} /></IconButton>}>
                          {auth.can('flows.teach') ? <ActionMenuItem icon={<SlidersHorizontal size={13} />} to={`/flows/${flow.id}/teach`} testId="row-teach">{t('flows.teach')}</ActionMenuItem> : null}
                          <ActionMenuItem icon={<Gem size={13} />} to={`/flows/${flow.id}/golden`} testId="row-golden">{t('flows.golden')}</ActionMenuItem>
                          <ActionMenuItem icon={<BarChart3 size={13} />} to={`/flows/${flow.id}/stats`} testId="row-stats">{t('stats.open')}</ActionMenuItem>
                          <ActionMenuSeparator />
                          <ActionMenuItem icon={<Download size={13} />} onClick={() => void onExport(flow)} title={t('flows.exportHint')} testId="row-export">{t('flows.export')}</ActionMenuItem>
                          <ActionMenuItem icon={<Copy size={13} />} onClick={() => void onDuplicate(flow)} testId="row-duplicate">{t('common.duplicate')}</ActionMenuItem>
                          <ActionMenuSeparator />
                          <ActionMenuItem icon={<Trash2 size={13} />} danger disabled={readOnly(flow)} title={readOnly(flow) ? t('flows.readOnly') : undefined} onClick={() => setPendingDelete(flow)} testId="row-delete">{t('common.delete')}</ActionMenuItem>
                        </ActionMenu>
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
        open={creating !== null}
        onClose={() => { setCreating(null); setNameError(null) }}
        title={creating === 'advanced' ? t('flows.createAdvancedTitle') : t('flows.createInspectionTitle')}
        description={creating === 'advanced' ? t('flows.createAdvancedHint') : t('flows.createInspectionHint')}
        dirty={Boolean(form.name || form.description)}
        footer={(close) => (
          <>
            <Button onClick={close}>{t('common.cancel')}</Button>
            <Button variant="primary" loading={create.isPending} onClick={() => void onCreate()}>{t('common.create')}</Button>
          </>
        )}
      >
        <div className="space-y-3">
          <TextInput label={t('common.name')} required autoFocus value={form.name} error={nameError ?? undefined} onChange={(e) => { setForm({ ...form, name: e.target.value }); if (nameError) setNameError(null) }} onKeyDown={(e) => e.key === 'Enter' && void onCreate()} data-testid="flow-create-name" />
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
          <Select label={t('flows.importSource')} value={importSource} placeholder={t('flows.importSourceNone')} onChange={(e) => setImportSource(e.target.value)} options={(sources.data?.items ?? []).map((src) => ({ value: String(src.id), label: `${src.name} (${src.kind})` }))} data-testid="import-source" />
        </div>
      </Modal>

      <RecipeDrawer open={recipeFlow !== null} onClose={() => setRecipeFlow(null)} flowId={recipeFlow?.id ?? 0} readOnly={recipeFlow ? readOnly(recipeFlow) : true} />
      <TemplateGallery open={gallery} onClose={() => setGallery(false)} mode="create" onPick={onFromTemplate} />
      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void onDelete()} title={t('flows.deleteTitle')} message={t('flows.deleteMessage', { name: pendingDelete?.name ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </Page>
  )
}
