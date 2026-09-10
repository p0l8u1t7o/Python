/**
 * 參數卡（TeachPage）`/flows/:id/teach`：全流程所有 `teach=true` 的參數，換線調機不必開畫布。
 *
 * 三欄：左＝步驟清單（點選聚焦、狀態點、耗時）；中＝目前聚焦步驟的教導參數（一次只顯示一個步驟，
 * 標籤在上、說明在下）；右＝影像視窗（大）＋該步驟結果摘要。頂列兩排：動作／配方。
 *
 * - 圖來自 lib/flowDraft.ts 的共享草稿（與編輯器／工具頁同一份）；沒選配方時改動寫進草稿（Ctrl+S 存到圖）。
 * - 選了配方（編輯對象）：欄位顯示配方覆寫值（沒有覆寫的參數顯示圖值），改動寫進配方的 param_overrides；
 *   試跑時把覆寫疊到圖上再送（applyOverrides，與後端 apply_recipe 同語意），未儲存的覆寫也看得到效果。
 * - 儲存到配方／存為新配方都先走「儲存範圍 Check List」（useSaveCheck），只送勾選的項目。
 * - 「管理配方」開 RecipeDrawer（與流程頁同一個側滑面板）；「綁定」顯示目前 is_default 的配方。
 * - 改動 → 250 ms 後以 until_node=該步驟＋reuse_image_ref（暫存影像或上次來源影像）＋analysis:false 試跑。
 * - 「標記為已教導」PATCH commissioned=true；未教導的流程執行時 RunReport.warnings 會帶提醒（不阻擋）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useBlocker, useParams } from 'react-router-dom'
import { ArrowLeft, BookOpen, BookmarkPlus, CheckCircle2, CircleDashed, ImageUp, Loader2, Lock, Save, SlidersHorizontal, Undo2 } from 'lucide-react'

import { ScratchBadge } from '@/components/editor/EditorToolbar'
import type { InspectorActions } from '@/components/editor/ParamField'
import { ParamField } from '@/components/editor/ParamField'
import { formatValue } from '@/components/editor/ResultsPanel'
import { iconFor } from '@/components/editor/ToolNode'
import { useSaveConflictDialog } from '@/components/flow/SaveConflictDialog'
import { BoundBadge } from '@/components/recipes/BoundRecipeSelect'
import { RecipeDrawer, compactOverrides, countOverrides, useSaveCheck, type Overrides } from '@/components/recipes/RecipeDrawer'
import { Badge, Button, ErrorState, LoadingState, Modal, StatusBadge, TextInput } from '@/components/ui'
import { ImageViewer } from '@/components/viewer/ImageViewer'
import { imageUrl } from '@/lib/api'
import { useConfirm } from '@/lib/useConfirm'
import { errorMessage } from '@/lib/errors'
import { getSession, patchDraftNode, setDraft, updateSession, useFlowSession } from '@/lib/flowDraft'
import { applyOverrides, previewFlow, useFlow, useFlowMutations, useRecipeMutations, useRecipes, useScratchImage, useToolTypes } from '@/lib/queries'
import type { FlowGraph, NodeReport, RunReport, ToolTypeDef } from '@/lib/types'
import { isLockHolder, useAuth } from '@/providers/AuthProvider'
import { teachGroupsOf, type TeachGroup } from '@/lib/teachGroups'
import { useToast } from '@/providers/ToastProvider'
import { inputImage, sourceRefOf } from './FlowEditorPage'

const DEBOUNCE_MS = 250


/** 參數卡不做 ROI／範本編輯（教導參數都是數值／選項）。 */
const NO_ACTIONS: InspectorActions = { roiEditingKey: null, setRoiEditing: () => undefined, templateFromImage: () => undefined, templateKey: null, hasImage: false }

const DOT: Record<string, string> = { ok: 'bg-ok', ng: 'bg-warning', error: 'bg-critical', skipped: 'bg-line-strong' }

function TeachPageInner({ flowId }: { flowId: number }) {
  const { t } = useTranslation()
  const toast = useToast()
  const auth = useAuth()
  const catalogue = useToolTypes()
  const flow = useFlow(flowId)
  const recipes = useRecipes(flowId)
  const { patch } = useFlowMutations()
  const recipeMut = useRecipeMutations(flowId)
  const scratchUpload = useScratchImage()
  const session = useFlowSession(flowId)
  const { showConflict, dialog: saveConflictDialog } = useSaveConflictDialog()

  const [recipeId, setRecipeId] = useState<number | null>(null)
  const [overrides, setOverrides] = useState<Overrides>({})
  const [recipeDirty, setRecipeDirty] = useState(false)
  const [focusId, setFocusId] = useState<string | null>(null)
  const [reuse, setReuse] = useState(true)
  const [updating, setUpdating] = useState<string | null>(null)
  const [previewError, setPreviewError] = useState<string | null>(null)
  const [reports, setReports] = useState<Record<string, NodeReport>>({})
  const [runByNode, setRunByNode] = useState<Record<string, RunReport>>({})
  const [saving, setSaving] = useState(false)
  const [manageOpen, setManageOpen] = useState(false)
  const [saveAsOpen, setSaveAsOpen] = useState(false)
  const [saveAsName, setSaveAsName] = useState('')
  const scratchInput = useRef<HTMLInputElement>(null)
  const saveBaseline = useRef<string | null>(null)

  const defs = useMemo(() => {
    const map = new Map<string, ToolTypeDef>()
    for (const def of catalogue.data?.items ?? []) map.set(def.key, def)
    return map
  }, [catalogue.data])

  // ---- 草稿（與工具頁相同：讀 store 的即時值） ----
  useEffect(() => {
    const data = flow.data
    if (!data) return
    const draft = getSession(flowId).draft
    if (draft && draft.baseVersion === data.version) return
    setDraft(flowId, { baseVersion: data.version, graph: data.graph, name: data.name, description: data.description, dirty: false })
    saveBaseline.current = data.updated_at
  }, [flow.data, session.draft, flowId])

  useEffect(() => {
    if (flow.data) saveBaseline.current = flow.data.updated_at
  }, [flow.data])

  const draft = session.draft && flow.data && session.draft.baseVersion === flow.data.version ? session.draft : null
  const graph = draft?.graph
  const saveCheck = useSaveCheck(flowId, { graph, defs })
  const payloads = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n])), [graph])
  const edges = graph?.edges ?? []

  const groups = useMemo<TeachGroup[]>(() => teachGroupsOf(graph, defs), [graph, defs])

  useEffect(() => {
    if ((!focusId || !groups.some((g) => g.node.id === focusId)) && groups.length) setFocusId(groups[0].node.id)
  }, [groups, focusId])

  // ---- 配方（編輯對象） ----
  const recipeList = useMemo(() => recipes.data?.items ?? [], [recipes.data])
  const recipe = recipeId !== null ? recipeList.find((r) => r.id === recipeId) ?? null : null
  const { confirm, dialog } = useConfirm()
  const selectRecipe = useCallback(
    async (id: number | null) => {
      if (recipeDirty && !(await confirm(t('editor.leaveUnsaved'), { title: t('editor.leaveTitle'), confirmLabel: t('editor.leaveAnyway') }))) return
      setRecipeId(id)
      const r = id !== null ? recipeList.find((x) => x.id === id) : null
      setOverrides(r ? structuredClone(r.param_overrides ?? {}) : {})
      setRecipeDirty(false)
    },
    [recipeDirty, recipeList, t],
  )

  const execLocked = auth.lock.locked && auth.me?.kind !== 'integrator' && !isLockHolder(auth.me, auth.lock)
  // 參數卡頁是現場微調的地方：有 flows.teach 的人才能改（伺服器只放行標了 teach 的參數，沒有這個功能的角色會被 403）；
  // 「標記為已教導」是工程師的簽核動作，另外用 canCommission 控制。
  const readOnly = !auth.can('flows.teach')
  const canCommission = auth.isEngineer

  const loadServerConflict = useCallback(
    (details: { version: number; updated_at: string; graph: FlowGraph }) => {
      saveBaseline.current = details.updated_at
      setDraft(flowId, {
        baseVersion: details.version,
        graph: details.graph,
        name: flow.data?.name ?? '',
        description: flow.data?.description ?? '',
        dirty: false,
      })
      void flow.refetch()
    },
    [flow, flowId],
  )

  // ---- 試跑 ----
  const scratch = session.scratch
  const lastSourceRef = useMemo(() => sourceRefOf(session.previewRun, payloads), [session.previewRun, payloads])
  const pinnedRef = scratch?.ref ?? (reuse ? lastSourceRef : null)
  const pinnedRefRef = useRef(pinnedRef)
  pinnedRefRef.current = pinnedRef
  const effectiveGraphRef = useRef<FlowGraph | undefined>(undefined)
  effectiveGraphRef.current = graph ? (recipe ? applyOverrides(graph, overrides) : graph) : undefined

  const abortRef = useRef<AbortController | null>(null)
  const timerRef = useRef<number | undefined>(undefined)
  const runPreview = useCallback(
    async (untilNode: string | null) => {
      const g = effectiveGraphRef.current
      if (!g) return
      abortRef.current?.abort()
      const controller = new AbortController()
      abortRef.current = controller
      setUpdating(untilNode ?? '*')
      try {
        const result = await previewFlow({ flowId, graph: g, until_node: untilNode, analysis: false, reuse_image_ref: pinnedRefRef.current, signal: controller.signal })
        if (controller.signal.aborted) return
        updateSession(flowId, { previewRun: result })
        setReports((old) => ({ ...old, ...result.nodes }))
        setRunByNode((old) => {
          const next = { ...old }
          for (const id of Object.keys(result.nodes)) next[id] = result
          return next
        })
        setPreviewError(null)
      } catch (error) {
        if (controller.signal.aborted) return
        setPreviewError(errorMessage(error))
      } finally {
        if (abortRef.current === controller) {
          abortRef.current = null
          setUpdating(null)
        }
      }
    },
    [flowId],
  )
  const schedulePreview = useCallback(
    (nodeId: string) => {
      window.clearTimeout(timerRef.current)
      timerRef.current = window.setTimeout(() => void runPreview(nodeId), DEBOUNCE_MS)
    },
    [runPreview],
  )
  // 進頁面先整條跑一次，讓每個步驟都有狀態。
  const booted = useRef(false)
  useEffect(() => {
    if (!graph || defs.size === 0 || execLocked || booted.current) return
    booted.current = true
    void runPreview(null)
  }, [graph, defs, execLocked, runPreview])
  useEffect(
    () => () => {
      window.clearTimeout(timerRef.current)
      abortRef.current?.abort()
    },
    [],
  )

  // ---- 改值 ----
  const onChange = useCallback(
    (nodeId: string, key: string, value: unknown) => {
      if (readOnly) {
        toast.warning(t('teach.readOnlyHint'))
        return
      }
      if (recipe) {
        setOverrides((old) => ({ ...old, [nodeId]: { ...(old[nodeId] ?? {}), [key]: value } }))
        setRecipeDirty(true)
      } else {
        const node = payloads.get(nodeId)
        patchDraftNode(flowId, nodeId, { params: { ...(node?.params ?? {}), [key]: value } })
      }
      if (!execLocked) schedulePreview(nodeId)
    },
    [recipe, payloads, flowId, execLocked, schedulePreview, readOnly, toast, t],
  )
  const revert = useCallback(
    (nodeId: string, key: string) => {
      setOverrides((old) => {
        const p = { ...(old[nodeId] ?? {}) }
        delete p[key]
        return compactOverrides({ ...old, [nodeId]: p })
      })
      setRecipeDirty(true)
      if (!execLocked) schedulePreview(nodeId)
    },
    [execLocked, schedulePreview],
  )

  // ---- 儲存（配方走 Check List） ----
  const save = useCallback(async () => {
    if (readOnly) {
      toast.warning(t('flows.readOnlyHint'))
      return
    }
    if (recipe) {
      await saveCheck.start(overrides, async (o) => {
        await recipeMut.patch.mutateAsync({ id: recipe.id, param_overrides: o })
        setOverrides(o)
        setRecipeDirty(false)
        toast.success(t('teach.savedRecipe', { name: recipe.name }))
      }, t('recipes.checkTitleSave', { name: recipe.name }))
      return
    }
    if (!draft) return
    setSaving(true)
    try {
      const saved = await patch.mutateAsync({ id: flowId, name: draft.name.trim() || t('editor.untitled'), description: draft.description, graph: draft.graph, expected_updated_at: saveBaseline.current })
      saveBaseline.current = saved.updated_at
      setDraft(flowId, { ...draft, baseVersion: saved.version, dirty: false })
      toast.success(t('editor.toast.saved'))
    } catch (error) {
      if (!showConflict(error, {
        flowId,
        graph: draft.graph,
        loadServer: loadServerConflict,
        overwrite: async (updatedAt) => {
          const saved = await patch.mutateAsync({ id: flowId, name: draft.name.trim() || t('editor.untitled'), description: draft.description, graph: draft.graph, expected_updated_at: updatedAt })
          saveBaseline.current = saved.updated_at
          setDraft(flowId, { ...draft, baseVersion: saved.version, dirty: false })
          toast.success(t('editor.toast.saved'))
        },
      })) toast.error(errorMessage(error))
    } finally {
      setSaving(false)
    }
  }, [readOnly, recipe, overrides, draft, saveCheck, recipeMut.patch, patch, flowId, toast, t, showConflict, loadServerConflict])

  const saveRef = useRef(save)
  saveRef.current = save
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 's') {
        event.preventDefault()
        void saveRef.current()
      }
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [])

  // ---- 離開攔截：圖草稿回編輯器不算（草稿帶回去）；配方未儲存一律問 ----
  const editorPath = `/flows/${flowId}`
  const draftDirty = Boolean(draft?.dirty)
  const blocker = useBlocker(
    useCallback(
      ({ currentLocation, nextLocation }: { currentLocation: { pathname: string }; nextLocation: { pathname: string } }) => {
        if (currentLocation.pathname === nextLocation.pathname) return false
        if (recipeDirty) return true
        return draftDirty && nextLocation.pathname !== editorPath && !nextLocation.pathname.startsWith(`${editorPath}/`)
      },
      [recipeDirty, draftDirty, editorPath],
    ),
  )
  useEffect(() => {
    if (blocker.state !== 'blocked') return
    void confirm(t('editor.leaveUnsaved'), { title: t('editor.leaveTitle'), confirmLabel: t('editor.leaveAnyway') }).then((ok) => (ok ? blocker.proceed() : blocker.reset()))
  }, [blocker, t, confirm])

  // ---- 已教導 ----
  async function setCommissioned(value: boolean) {
    try {
      const saved = await patch.mutateAsync({ id: flowId, commissioned: value, expected_updated_at: saveBaseline.current })
      saveBaseline.current = saved.updated_at
      toast.success(value ? t('teach.markedCommissioned') : t('teach.unmarkedCommissioned'))
    } catch (error) {
      const currentGraph = draft?.graph ?? flow.data?.graph ?? { nodes: [], edges: [] }
      if (!showConflict(error, {
        flowId,
        graph: currentGraph,
        loadServer: loadServerConflict,
        overwrite: async (updatedAt) => {
          const saved = await patch.mutateAsync({ id: flowId, commissioned: value, expected_updated_at: updatedAt })
          saveBaseline.current = saved.updated_at
          toast.success(value ? t('teach.markedCommissioned') : t('teach.unmarkedCommissioned'))
        },
      })) toast.error(errorMessage(error))
    }
  }

  // ---- 暫存影像 ----
  async function uploadScratch(file: File) {
    try {
      const info = await scratchUpload.mutateAsync({ flowId, file })
      updateSession(flowId, { scratch: info })
      toast.success(t('editor.toast.scratchUploaded', { name: info.name, w: info.width, h: info.height }))
      pinnedRefRef.current = info.ref
      void runPreview(null)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }

  // ---- 存為新配方（Check List） ----
  async function saveAsRecipe() {
    const name = saveAsName.trim()
    if (!name) return toast.error(t('flows.nameRequired'))
    let param_overrides: Overrides
    if (recipe) param_overrides = compactOverrides(overrides)
    else {
      // 圖模式：所有教導參數的目前值（Check List 會把與圖相同的標成 unchanged，預設不勾）
      param_overrides = {}
      for (const g of groups) for (const p of g.params) (param_overrides[g.node.id] ??= {})[p.key] = g.node.params?.[p.key] ?? p.default ?? null
    }
    setSaveAsOpen(false)
    await saveCheck.start(param_overrides, async (o) => {
      const r = await recipeMut.create.mutateAsync({ name, param_overrides: o, is_default: recipeList.length === 0 })
      toast.success(t('teach.recipeCreated', { name }))
      setSaveAsName('')
      setRecipeId(r.id)
      setOverrides(structuredClone(r.param_overrides ?? {}))
      setRecipeDirty(false)
    }, t('recipes.checkTitleCreate', { name }))
  }

  if (catalogue.isPending || flow.isPending || !draft || !graph) return <LoadingState />
  if (catalogue.isError || flow.isError) return <ErrorState error={flow.error ?? catalogue.error} onRetry={() => void flow.refetch()} />

  const dirty = recipe ? recipeDirty : draftDirty
  const commissioned = flow.data?.commissioned !== false
  const focusGroup = groups.find((g) => g.node.id === focusId) ?? null
  const focusReport = focusId ? reports[focusId] : undefined
  const focusRun = focusId ? runByNode[focusId] : undefined
  const focusInput = focusRun && focusReport && focusId ? inputImage(focusRun, focusId, focusReport, edges, defs, payloads) : null
  const badge = focusReport ? { text: `${t(`status.${focusReport.status}`)} · ${Math.round(focusReport.duration_ms)} ms`, tone: (focusReport.status === 'ok' ? 'ok' : focusReport.status === 'ng' || focusReport.status === 'error' ? 'ng' : 'neutral') as 'ok' | 'ng' | 'neutral' } : null
  const FocusIcon = focusGroup ? iconFor(focusGroup.def.icon) : SlidersHorizontal

  return (
    <div className="flex h-full flex-col" data-testid="teach-page">
      {dialog}
      <header className="border-b border-line bg-surface" data-testid="teach-header">
        {/* 第一排：動作 */}
        <div className="flex flex-wrap items-center gap-1.5 px-3 py-1.5">
          <Link to={editorPath} className="btn-secondary !h-8 !px-2.5 !text-xs" data-testid="btn-back"><ArrowLeft size={14} /> {t('teach.back')}</Link>
          <span className="flex items-center gap-1.5 text-sm font-semibold"><SlidersHorizontal size={15} className="text-brand" /> {t('teach.title')} <span className="font-normal text-muted">· {draft.name}</span></span>
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <span title={t('teach.saveShortcut')}>
            <Button size="sm" variant={dirty ? 'primary' : 'secondary'} icon={<Save size={14} />} loading={saving} disabled={readOnly} onClick={() => void save()} data-testid="teach-save">
              {recipe ? t('teach.saveRecipe') : t('teach.saveGraph')}
            </Button>
          </span>
          {dirty ? <span className="text-[11px] text-warning">{t('teach.unsaved')}</span> : null}
          {readOnly ? <span className="flex items-center gap-1 text-[11px] text-warning" data-testid="teach-readonly"><Lock size={11} /> {t('teach.readOnlyHint')}</span> : null}
          <label className="flex items-center gap-1 text-[11px] text-muted" title={t('teach.lastImageHint')}>
            <input type="checkbox" className="accent-[var(--brand)]" checked={reuse} disabled={Boolean(scratch) || !lastSourceRef} onChange={(e) => setReuse(e.target.checked)} />
            {t('teach.lastImage')}
          </label>
          {scratch ? (
            <ScratchBadge scratch={scratch} onClear={() => updateSession(flowId, { scratch: null })} />
          ) : (
            <Button size="sm" icon={<ImageUp size={14} />} loading={scratchUpload.isPending} onClick={() => scratchInput.current?.click()} data-testid="teach-scratch">{t('editor.scratchUpload')}</Button>
          )}
          <input ref={scratchInput} type="file" accept="image/*" className="hidden" data-testid="scratch-input" onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ''; if (f) void uploadScratch(f) }} />
          <span className="ml-auto flex items-center gap-1.5">
            {updating ? <span className="flex items-center gap-1 text-[11px] text-brand" data-testid="teach-updating"><Loader2 size={12} className="animate-spin" /> {t('teach.updating')}</span> : null}
            {previewError ? <span className="max-w-72 truncate text-[11px] text-critical" title={previewError} data-testid="teach-preview-error">{previewError}</span> : null}
            {commissioned ? (
              <>
                <Badge tone="ok"><CheckCircle2 size={11} /> {t('teach.commissioned')}</Badge>
                <Button size="xs" variant="ghost" disabled={!canCommission} loading={patch.isPending} title={t('teach.commissionedHint')} onClick={() => void setCommissioned(false)} data-testid="teach-unmark">{t('teach.unmarkCommissioned')}</Button>
              </>
            ) : (
              <>
                <Badge tone="warning"><CircleDashed size={11} /> {t('teach.notCommissioned')}</Badge>
                <Button size="sm" variant="primary" icon={<CheckCircle2 size={14} />} disabled={!canCommission} loading={patch.isPending} title={t('teach.notCommissionedHint')} onClick={() => void setCommissioned(true)} data-testid="teach-mark">{t('teach.markCommissioned')}</Button>
              </>
            )}
          </span>
        </div>
        {/* 第二排：配方 */}
        <div className="flex flex-wrap items-center gap-1.5 border-t border-line bg-surface-muted/40 px-3 py-1.5" data-testid="teach-recipe-row">
          <BoundBadge recipes={recipeList} />
          <span className="mx-1 h-5 w-px bg-line" aria-hidden />
          <label className="flex items-center gap-1 text-[11px] text-muted" title={t('teach.recipeSelectHint')}>
            {t('teach.editTarget')}
            <select className="input !h-8 !w-44 !py-0 text-xs" value={recipeId ?? ''} onChange={(e) => selectRecipe(e.target.value === '' ? null : Number(e.target.value))} data-testid="teach-recipe">
              <option value="">{t('teach.recipeGraph')}</option>
              {recipeList.map((r) => <option key={r.id} value={r.id}>{r.name}{r.is_default ? ` · ${t('recipes.boundTag')}` : ''}</option>)}
            </select>
          </label>
          {recipe ? <span className="tnum text-[11px] text-brand" data-testid="teach-override-count">{t('teach.overrideCount', { count: countOverrides(overrides) })}</span> : null}
          <Button size="sm" icon={<BookmarkPlus size={14} />} disabled={!canCommission} title={t('teach.recipeSaveAsHint')} onClick={() => setSaveAsOpen(true)} data-testid="teach-save-as">{t('teach.recipeSaveAs')}</Button>
          <Button size="sm" icon={<BookOpen size={14} />} onClick={() => setManageOpen(true)} data-testid="teach-manage">{t('teach.recipeManage')}{recipeList.length ? ` (${recipeList.length})` : ''}</Button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
        {/* 左：步驟清單 */}
        <aside className="w-full md:w-60 shrink-0 md:overflow-y-auto border-b md:border-b-0 md:border-r border-line bg-surface" data-testid="teach-steps">
          <p className="border-b border-line px-3 py-2 text-xs font-semibold text-heading">{t('teach.step')} <span className="tnum font-normal text-muted">({groups.length})</span></p>
          {groups.length === 0 ? (
            <div className="m-3 rounded-md border border-dashed border-line p-3 text-xs text-muted">
              <p>{t('teach.noTeachParams')}</p>
              <p className="mt-1">{t('teach.noTeachParamsHint')}</p>
            </div>
          ) : null}
          <ul>
            {groups.map(({ node, def, params }, i) => {
              const report = reports[node.id]
              const Icon = iconFor(def.icon)
              const focused = focusId === node.id
              const changed = recipe ? Object.keys(overrides[node.id] ?? {}).length : 0
              return (
                <li key={node.id}>
                  <button type="button" className={`relative flex w-full items-center gap-2 px-3 py-2 text-left transition-colors ${focused ? 'bg-brand-soft/60' : 'hover:bg-surface-muted'}`} onClick={() => setFocusId(node.id)} data-testid="teach-group" data-node-id={node.id} data-focused={focused ? 'true' : 'false'}>
                    {focused ? <span className="absolute inset-y-0 left-0 w-[3px] bg-brand" aria-hidden /> : null}
                    <span className="tnum w-4 text-[10px] text-subtle">{i + 1}</span>
                    <span className={`flex size-6 shrink-0 items-center justify-center rounded-md ${focused ? 'bg-brand text-on-brand' : 'bg-surface-muted text-muted'}`}><Icon size={13} /></span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm font-medium">{node.label || def.label}</span>
                      <span className="block truncate text-[10px] text-muted">{def.label} · {params.length} {t('teach.paramCount')}{changed ? ` · ${t('teach.overrideCount', { count: changed })}` : ''}</span>
                    </span>
                    <span className="flex shrink-0 flex-col items-end gap-0.5" data-testid="teach-status">
                      {updating === node.id ? <Loader2 size={12} className="animate-spin text-brand" /> : <span className={`size-2.5 rounded-full ${report ? DOT[report.status] ?? 'bg-line-strong' : 'bg-line'}`} title={report?.status ?? t('teach.noResult')} />}
                      <span className="tnum text-[10px] text-muted">{report ? `${Math.round(report.duration_ms)} ms` : '—'}</span>
                    </span>
                  </button>
                </li>
              )
            })}
          </ul>
        </aside>

        {/* 中：聚焦步驟的教導參數 */}
        <div className="w-full shrink-0 overflow-y-auto border-b border-line bg-surface md:w-[360px] md:border-b-0 md:border-r 2xl:w-[420px]" data-testid="teach-params">
          {focusGroup ? (
            <section data-node-id={focusGroup.node.id}>
              <div className="border-b border-line px-5 py-3">
                <div className="flex items-center gap-2">
                  <span className="flex size-8 items-center justify-center rounded-md bg-brand-soft text-brand"><FocusIcon size={16} /></span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-base font-semibold text-heading">{focusGroup.node.label || focusGroup.def.label}</p>
                    <p className="truncate font-mono text-[11px] text-muted">{focusGroup.def.label} · {focusGroup.node.id}</p>
                  </div>
                  {focusGroup.node.enabled === false ? <Badge>{t('teach.nodeDisabled')}</Badge> : null}
                  {focusReport ? <StatusBadge status={focusReport.status} /> : null}
                </div>
                {focusReport?.message && focusReport.status !== 'ok' ? <p className={`mt-2 rounded-md px-2.5 py-1.5 text-xs ${focusReport.status === 'error' ? 'bg-critical-soft text-critical' : 'bg-warning-soft text-warning'}`} data-testid="teach-message">{focusReport.message}</p> : null}
                {recipe ? <p className="mt-2 text-[11px] text-brand">{t('teach.editingRecipe', { name: recipe.name })}</p> : <p className="mt-2 text-[11px] text-muted">{t('teach.editingGraph')}</p>}
              </div>
              <div className="space-y-6 px-5 py-5">
                {focusGroup.params.map((p) => {
                  const node = focusGroup.node
                  const graphValue = node.params?.[p.key] ?? p.default
                  const hasOverride = Boolean(recipe) && overrides[node.id] !== undefined && p.key in (overrides[node.id] ?? {})
                  const value = hasOverride ? overrides[node.id][p.key] : graphValue
                  return (
                    <div key={p.key} data-param={p.key} className={hasOverride ? 'rounded-md border-l-2 border-brand pl-3' : ''}>
                      <ParamField param={p} value={value} actions={NO_ACTIONS} onChange={(v) => onChange(node.id, p.key, v)} />
                      {hasOverride ? (
                        <p className="mt-1 flex items-center gap-1 text-[11px] text-brand">
                          {t('teach.valueFromRecipe')} · {t('teach.valueFromGraph', { value: formatValue(graphValue) })}
                          <button type="button" className="ml-1 inline-flex items-center gap-0.5 text-muted hover:text-content" onClick={() => revert(node.id, p.key)} title={t('teach.revertToGraph')}><Undo2 size={10} /> {t('teach.revertToGraph')}</button>
                        </p>
                      ) : null}
                    </div>
                  )
                })}
              </div>
            </section>
          ) : (
            <p className="p-5 text-sm text-muted">{t('teach.pickStep')}</p>
          )}
        </div>

        {/* 右：影像視窗（大）＋結果摘要 */}
        <div className="flex min-w-0 flex-1 flex-col" data-testid="teach-viewer">
          <div className="relative min-h-0 flex-1">
            <ImageViewer src={focusInput?.ref ? imageUrl(focusInput.ref, 1600) : null} imageWidth={focusInput?.width ?? 0} imageHeight={focusInput?.height ?? 0} overlays={focusReport?.overlays ?? []} toolbar className="h-full w-full" badge={badge} stateKey={`teach:${flowId}`} />
            <span className="pointer-events-none absolute left-2 top-8 rounded bg-black/50 px-1.5 py-0.5 text-[11px] text-white/90">
              {focusGroup ? `${t('teach.focused')}: ${focusGroup.node.label || focusGroup.def.label}` : t('teach.viewerHint')}
            </span>
          </div>
          <div className="h-40 shrink-0 overflow-y-auto border-t border-line bg-surface px-4 py-2 text-xs" data-testid="teach-outputs">
            <p className="mb-1 font-semibold text-heading">{t('teach.resultSummary')}</p>
            {focusReport ? (
              <div className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
                <span className="text-muted">{t('editor.result.status')}</span>
                <span><StatusBadge status={focusReport.status} /> <span className="tnum text-muted">{focusReport.duration_ms.toFixed(1)} ms</span>{focusReport.branch ? <span className="ml-2 font-mono text-muted">{focusReport.branch}</span> : null}</span>
                {focusReport.message ? (<><span className="text-muted">{t('editor.result.message')}</span><span className={focusReport.status === 'error' ? 'text-critical' : focusReport.status === 'ng' ? 'text-warning' : ''}>{focusReport.message}</span></>) : null}
                {Object.entries(focusReport.outputs).map(([k, v]) => (
                  <span key={k} className="contents"><span className="font-mono text-muted">{k}</span><span className="truncate font-mono">{formatValue(v)}</span></span>
                ))}
              </div>
            ) : (
              <p className="text-muted">{t('teach.noResult')}</p>
            )}
          </div>
        </div>
      </div>

      <RecipeDrawer open={manageOpen} onClose={() => { setManageOpen(false); if (recipe) { const r = recipeList.find((x) => x.id === recipe.id); if (r && !recipeDirty) setOverrides(structuredClone(r.param_overrides ?? {})) } }} flowId={flowId} readOnly={!canCommission} graphOverride={graph} />
      {saveCheck.modal}
      {saveConflictDialog}
      <Modal
        open={saveAsOpen}
        onClose={() => setSaveAsOpen(false)}
        title={t('teach.recipeSaveAs')}
        description={t('teach.recipeSaveAsHint')}
        size="sm"
        footer={
          <>
            <Button onClick={() => setSaveAsOpen(false)}>{t('common.cancel')}</Button>
            <Button variant="primary" onClick={() => void saveAsRecipe()} data-testid="teach-save-as-confirm">{t('recipes.nextCheck')}</Button>
          </>
        }
      >
        <TextInput label={t('teach.recipeName')} autoFocus value={saveAsName} onChange={(e) => setSaveAsName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void saveAsRecipe()} data-testid="teach-save-as-name" />
      </Modal>
    </div>
  )
}

export function TeachPage() {
  const { flowId } = useParams<{ flowId: string }>()
  const id = Number(flowId)
  if (!flowId || Number.isNaN(id)) return null
  return <TeachPageInner key={id} flowId={id} />
}
