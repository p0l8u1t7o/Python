/**
 * 配方側滑面板（RecipeDrawer）：流程頁列上「配方」與參數卡頁「管理配方」共用。
 *  - 綁定配方下拉（BoundRecipeSelect）
 *  - 新增（可用目前圖值當覆寫：教導參數）／改名／複製／刪除／設綁定／匯出／全部匯出／匯入
 *  - 展開一個配方可編輯覆寫表；儲存與新增都先走「儲存範圍 Check List」（useSaveCheck，帶 include_all：
 *    流程所有參數都列出，教導參數在上、其他參數摺疊），只送勾選的項目（值＝清單上的值，unchanged 就是圖值）。
 */
import { useMemo, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Check, ChevronDown, ChevronRight, Copy, Download, Link2, Pencil, Plus, Save, Trash2, Upload, X } from 'lucide-react'

import { formatValue } from '@/components/editor/ResultsPanel'
import { Badge, Button, ConfirmDialog, IconButton, Select, TextInput } from '@/components/ui'
import { downloadFile } from '@/lib/api'
import { errorMessage } from '@/lib/errors'
import { paramVisible } from '@/lib/graphValidation'
import { checkRecipe, useFlow, useRecipeMutations, useRecipes, useToolTypes } from '@/lib/queries'
import type { FlowGraph, FlowRecipe, RecipeCheckItem, ToolParam, ToolTypeDef } from '@/lib/types'
import { topoOrder } from '@/pages/FlowEditorPage'
import { useToast } from '@/providers/ToastProvider'
import { BoundRecipeSelect } from './BoundRecipeSelect'
import { RecipeCheckListModal } from './RecipeCheckList'
import { RecipeImportModal } from './RecipeImportModal'

export type Overrides = Record<string, Record<string, unknown>>

export function countOverrides(overrides: Overrides | null | undefined): number {
  return Object.values(overrides ?? {}).reduce((n, p) => n + Object.keys(p ?? {}).length, 0)
}

export function compactOverrides(overrides: Overrides): Overrides {
  const out: Overrides = {}
  for (const [nid, p] of Object.entries(overrides)) if (p && Object.keys(p).length) out[nid] = p
  return out
}

/** 只留勾選的項目（值取自檢查清單，與送檢的一致）。 */
export function pickOverrides(items: RecipeCheckItem[], keys: string[]): Overrides {
  const on = new Set(keys)
  const out: Overrides = {}
  for (const it of items) if (on.has(it.key)) (out[it.node_id] ??= {})[it.param] = it.value
  return out
}

/** 條件隱藏（paramVisible=false）的教導參數：使用者在參數卡看不到，降到「其他參數」區（teach=false）。 */
function demoteHiddenParams(items: RecipeCheckItem[], graph: FlowGraph | undefined, defs: Map<string, ToolTypeDef> | undefined): RecipeCheckItem[] {
  if (!graph || !defs) return items
  return items.map((it) => {
    if (it.teach !== true) return it
    const node = graph.nodes.find((n) => n.id === it.node_id)
    const param = node ? defs.get(node.type)?.params.find((p) => p.key === it.param) : undefined
    return param && !paramVisible(param, node?.params ?? {}) ? { ...it, teach: false } : it
  })
}

/**
 * 儲存範圍 Check List 流程：start(overrides, then) → 檢查（include_all）→ 使用者勾選 → then(只含勾選的覆寫)。
 * ctx.graph／ctx.defs 用來把條件隱藏的教導參數降到「其他參數」區。
 */
export function useSaveCheck(flowId: number, ctx: { graph?: FlowGraph; defs?: Map<string, ToolTypeDef> } = {}) {
  const { t } = useTranslation()
  const toast = useToast()
  const [state, setState] = useState<{ title: string; items: RecipeCheckItem[]; then: (o: Overrides) => Promise<void> } | null>(null)
  const [loading, setLoading] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  async function start(overrides: Overrides, then: (o: Overrides) => Promise<void>, title?: string) {
    setState({ title: title ?? t('recipes.checkTitle'), items: [], then })
    setLoading(true)
    try {
      const res = await checkRecipe(flowId, compactOverrides(overrides), { include_all: true })
      const items = demoteHiddenParams(res.items, ctx.graph, ctx.defs)
      setState((s) => (s ? { ...s, items } : s))
    } catch (error) {
      toast.error(errorMessage(error))
      setState(null)
    } finally {
      setLoading(false)
    }
  }
  async function confirm(keys: string[]) {
    if (!state) return
    setSubmitting(true)
    try {
      await state.then(pickOverrides(state.items, keys))
      setState(null)
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setSubmitting(false)
    }
  }
  const modal: ReactNode = <RecipeCheckListModal open={state !== null} onClose={() => setState(null)} title={state?.title ?? ''} items={state?.items ?? []} loading={loading} submitting={submitting} confirmLabel={t('recipes.saveSelected')} onConfirm={(keys) => void confirm(keys)} />
  return { start, modal, active: state !== null }
}

function valueText(value: unknown): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

function parseValue(text: string, param: ToolParam | undefined): unknown {
  const s = text.trim()
  if (!s) return null
  if (param && (param.kind === 'number' || param.kind === 'range')) {
    const n = Number(s)
    return Number.isFinite(n) ? n : s
  }
  if (param && (param.kind === 'text' || param.kind === 'select' || param.kind === 'output_key' || param.kind === 'multiline' || param.kind === 'expression')) return s
  try {
    return JSON.parse(s)
  } catch {
    return s
  }
}

interface Row {
  node: string
  param: string
  value: string
}

/** 目前圖上所有教導參數的值（新增配方「以圖值作為覆寫」用）。 */
export function teachOverridesOf(graph: FlowGraph | undefined, defs: Map<string, ToolTypeDef>): Overrides {
  const out: Overrides = {}
  if (!graph) return out
  for (const id of topoOrder(graph.nodes, graph.edges)) {
    const node = graph.nodes.find((n) => n.id === id)
    const def = node ? defs.get(node.type) : undefined
    if (!node || !def) continue
    for (const p of def.params) {
      if (!p.teach || !paramVisible(p, node.params ?? {})) continue
      const v = node.params?.[p.key] ?? p.default
      if (v !== undefined) (out[node.id] ??= {})[p.key] = v
    }
  }
  return out
}

function RecipeRow({ flowId, recipe, graph, defs, readOnly, expanded, onToggle, onSave, onExport, onDuplicate, onDelete, onBind }: { flowId: number; recipe: FlowRecipe; graph: FlowGraph | undefined; defs: Map<string, ToolTypeDef>; readOnly: boolean; expanded: boolean; onToggle: () => void; onSave: (overrides: Overrides, meta: { name: string; description: string }) => void; onExport: () => void; onDuplicate: () => void; onDelete: () => void; onBind: () => void }) {
  const { t } = useTranslation()
  const { patch } = useRecipeMutations(flowId)
  const toast = useToast()
  const [renaming, setRenaming] = useState(false)
  const [name, setName] = useState(recipe.name)
  const [rows, setRows] = useState<Row[]>(() => Object.entries(recipe.param_overrides ?? {}).flatMap(([node, p]) => Object.entries(p ?? {}).map(([param, value]) => ({ node, param, value: valueText(value) }))))
  const [dirty, setDirty] = useState(false)
  const nodeOptions = (graph?.nodes ?? []).filter((n) => defs.has(n.type)).map((n) => ({ value: n.id, label: `${n.label || defs.get(n.type)?.label || n.id} (${n.id})` }))
  const paramsOf = (nodeId: string): ToolParam[] => {
    const node = graph?.nodes.find((n) => n.id === nodeId)
    return node ? (defs.get(node.type)?.params ?? []) : []
  }
  function toOverrides(): Overrides {
    const out: Overrides = {}
    for (const row of rows) {
      if (!row.node || !row.param) continue
      const param = paramsOf(row.node).find((p) => p.key === row.param)
      ;(out[row.node] ??= {})[row.param] = parseValue(row.value, param)
    }
    return out
  }
  async function rename() {
    const next = name.trim()
    if (!next || next === recipe.name) return setRenaming(false)
    try {
      await patch.mutateAsync({ id: recipe.id, name: next })
      toast.success(t('recipes.renamed', { name: next }))
      setRenaming(false)
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  return (
    <li className={`rounded-md border ${expanded ? 'border-brand/50' : 'border-line'}`} data-testid="recipe-item" data-recipe-id={recipe.id} data-bound={recipe.is_default ? 'true' : 'false'}>
      <div className="flex items-center gap-1.5 px-2 py-1.5">
        <button type="button" className="btn-icon !p-1" onClick={onToggle} aria-expanded={expanded} title={t('recipes.editValues')} data-testid="recipe-expand">
          {expanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        </button>
        {renaming ? (
          <span className="flex min-w-0 flex-1 items-center gap-1">
            <input className="input !h-7 !py-0 text-xs" value={name} autoFocus onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter') void rename(); if (e.key === 'Escape') setRenaming(false) }} data-testid="recipe-rename-input" />
            <IconButton size="sm" label={t('common.save')} onClick={() => void rename()} data-testid="recipe-rename-save"><Check size={14} /></IconButton>
            <IconButton size="sm" label={t('common.cancel')} onClick={() => { setName(recipe.name); setRenaming(false) }}><X size={14} /></IconButton>
          </span>
        ) : (
          <span className="flex min-w-0 flex-1 items-center gap-2">
            <span className="truncate text-sm font-medium" data-testid="recipe-name">{recipe.name}</span>
            {recipe.is_default ? <Badge tone="brand"><Link2 size={10} /> {t('recipes.boundTag')}</Badge> : null}
            <span className="tnum text-[10px] text-muted">{t('recipes.overrideCount', { count: countOverrides(recipe.param_overrides) })}</span>
          </span>
        )}
        <span className="flex shrink-0 items-center">
          {!recipe.is_default ? <IconButton size="sm" label={t('recipes.setBound')} disabled={readOnly} onClick={onBind} data-testid="recipe-bind"><Link2 size={14} /></IconButton> : null}
          <IconButton size="sm" label={t('recipes.rename')} disabled={readOnly} onClick={() => setRenaming(true)} data-testid="recipe-rename"><Pencil size={14} /></IconButton>
          <IconButton size="sm" label={t('recipes.duplicate')} disabled={readOnly} onClick={onDuplicate} data-testid="recipe-duplicate"><Copy size={14} /></IconButton>
          <IconButton size="sm" label={t('recipes.export')} onClick={onExport} data-testid="recipe-export"><Download size={14} /></IconButton>
          <IconButton size="sm" label={t('recipes.delete')} disabled={readOnly} onClick={onDelete} data-testid="recipe-delete"><Trash2 size={14} className="text-critical" /></IconButton>
        </span>
      </div>
      {expanded ? (
        <div className="space-y-2 border-t border-line px-2 py-2" data-testid="recipe-detail">
          {recipe.description ? <p className="text-xs text-muted">{recipe.description}</p> : null}
          <div className="flex items-center justify-between">
            <p className="label !mb-0">{t('teach.recipeOverrides')}</p>
            <span className="flex gap-1">
              <Button size="xs" disabled={readOnly} onClick={() => { const next = [...rows]; for (const [nid, p] of Object.entries(teachOverridesOf(graph, defs))) for (const [k, v] of Object.entries(p)) if (!next.some((r) => r.node === nid && r.param === k)) next.push({ node: nid, param: k, value: valueText(v) }); setRows(next); setDirty(true) }} title={t('teach.recipeFillHint')} data-testid="recipe-fill">{t('teach.recipeFillFromGraph')}</Button>
              <Button size="xs" disabled={readOnly} onClick={() => { setRows([...rows, { node: nodeOptions[0]?.value ?? '', param: '', value: '' }]); setDirty(true) }} data-testid="recipe-add-row">{t('teach.overrideAdd')}</Button>
            </span>
          </div>
          <table className="w-full text-xs" data-testid="recipe-overrides">
            <thead className="text-[10px] uppercase text-subtle">
              <tr>
                <th className="px-1 py-1 text-left font-medium">{t('teach.overrideNode')}</th>
                <th className="px-1 py-1 text-left font-medium">{t('teach.overrideParam')}</th>
                <th className="px-1 py-1 text-left font-medium">{t('teach.overrideValue')}</th>
                <th className="px-1 py-1" />
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {rows.length === 0 ? <tr><td colSpan={4} className="px-1 py-3 text-muted">{t('teach.overrideNone')}</td></tr> : null}
              {rows.map((row, i) => {
                const params = paramsOf(row.node)
                const graphNode = graph?.nodes.find((n) => n.id === row.node)
                const graphValue = graphNode?.params?.[row.param] ?? params.find((p) => p.key === row.param)?.default
                return (
                  <tr key={i}>
                    <td className="px-1 py-1"><Select className="!py-1 text-xs" value={row.node} disabled={readOnly} options={nodeOptions} placeholder="—" onChange={(e) => { const next = [...rows]; next[i] = { ...row, node: e.target.value, param: '' }; setRows(next); setDirty(true) }} /></td>
                    <td className="px-1 py-1"><Select className="!py-1 text-xs" value={row.param} disabled={readOnly} options={params.map((p) => ({ value: p.key, label: `${p.label} (${p.key})${p.teach ? ' ★' : ''}` }))} placeholder="—" onChange={(e) => { const next = [...rows]; next[i] = { ...row, param: e.target.value, value: valueText(graphNode?.params?.[e.target.value] ?? params.find((p) => p.key === e.target.value)?.default) }; setRows(next); setDirty(true) }} /></td>
                    <td className="px-1 py-1">
                      <input className="input !py-1 font-mono text-xs" value={row.value} disabled={readOnly} onChange={(e) => { const next = [...rows]; next[i] = { ...row, value: e.target.value }; setRows(next); setDirty(true) }} data-testid="recipe-value" />
                      {row.param ? <p className="text-[10px] text-muted">{t('teach.valueFromGraph', { value: formatValue(graphValue) })}</p> : null}
                    </td>
                    <td className="px-1 py-1 text-right"><button type="button" className="btn-icon" title={t('teach.overrideRemove')} disabled={readOnly} onClick={() => { setRows(rows.filter((_, j) => j !== i)); setDirty(true) }}><Trash2 size={13} /></button></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
          {!readOnly ? <Button size="sm" variant={dirty ? 'primary' : 'secondary'} icon={<Save size={14} />} onClick={() => onSave(toOverrides(), { name: recipe.name, description: recipe.description })} data-testid="recipe-save">{t('recipes.saveWithCheck')}</Button> : null}
        </div>
      ) : null}
    </li>
  )
}

export function RecipeDrawer({ open, onClose, flowId, readOnly = false, graphOverride }: { open: boolean; onClose: () => void; flowId: number; readOnly?: boolean; /** 參數卡頁傳草稿圖（未儲存的值也算） */ graphOverride?: FlowGraph }) {
  const { t } = useTranslation()
  const toast = useToast()
  const flow = useFlow(open ? flowId : null)
  const catalogue = useToolTypes()
  const recipes = useRecipes(open ? flowId : null)
  const { create, patch, remove } = useRecipeMutations(flowId)
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [newName, setNewName] = useState('')
  const [fromGraph, setFromGraph] = useState(true)
  const [pendingDelete, setPendingDelete] = useState<FlowRecipe | null>(null)
  const [importOpen, setImportOpen] = useState(false)

  const defs = useMemo(() => {
    const map = new Map<string, ToolTypeDef>()
    for (const def of catalogue.data?.items ?? []) map.set(def.key, def)
    return map
  }, [catalogue.data])
  const graph = graphOverride ?? flow.data?.graph
  const saveCheck = useSaveCheck(flowId, { graph, defs })
  const list = recipes.data?.items ?? []
  const teachCount = useMemo(() => countOverrides(teachOverridesOf(graph, defs)), [graph, defs])

  if (!open) return null

  async function createRecipe() {
    const name = newName.trim()
    if (!name) return toast.error(t('flows.nameRequired'))
    const overrides = fromGraph ? teachOverridesOf(graph, defs) : {}
    const finish = async (o: Overrides) => {
      const r = await create.mutateAsync({ name, param_overrides: o, is_default: list.length === 0 })
      toast.success(t('teach.recipeCreated', { name }))
      setNewName('')
      setExpandedId(r.id)
    }
    if (countOverrides(overrides) === 0) {
      try {
        await finish({})
      } catch (error) {
        toast.error(errorMessage(error))
      }
      return
    }
    await saveCheck.start(overrides, finish, t('recipes.checkTitleCreate', { name }))
  }
  async function saveRecipe(recipe: FlowRecipe, overrides: Overrides) {
    await saveCheck.start(overrides, async (o) => {
      await patch.mutateAsync({ id: recipe.id, param_overrides: o })
      toast.success(t('teach.recipeUpdated', { name: recipe.name }))
    }, t('recipes.checkTitleSave', { name: recipe.name }))
  }
  async function bind(recipe: FlowRecipe) {
    try {
      await patch.mutateAsync({ id: recipe.id, is_default: true })
      toast.success(t('recipes.boundSet', { name: recipe.name }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  async function duplicate(recipe: FlowRecipe) {
    let name = `${recipe.name} (2)`
    let n = 2
    while (list.some((r) => r.name === name)) name = `${recipe.name} (${(n += 1)})`
    try {
      await create.mutateAsync({ name, description: recipe.description, param_overrides: structuredClone(recipe.param_overrides ?? {}), is_default: false })
      toast.success(t('recipes.duplicated', { name }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  async function exportOne(recipe: FlowRecipe) {
    try {
      await downloadFile(`/vision/flows/${flowId}/recipes/${recipe.id}/export`, `${flow.data?.name ?? flowId}.${recipe.name}.recipe.json`)
      toast.success(t('recipes.exported', { name: recipe.name }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  async function exportAll() {
    try {
      await downloadFile(`/vision/flows/${flowId}/recipes/export-all`, `${flow.data?.name ?? flowId}.recipes.json`)
      toast.success(t('recipes.exportedAll', { count: list.length }))
    } catch (error) {
      toast.error(errorMessage(error))
    }
  }
  async function doDelete() {
    if (!pendingDelete) return
    try {
      await remove.mutateAsync(pendingDelete.id)
      toast.success(t('teach.recipeDeleted'))
      if (expandedId === pendingDelete.id) setExpandedId(null)
    } catch (error) {
      toast.error(errorMessage(error))
    } finally {
      setPendingDelete(null)
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/40" onClick={onClose} aria-hidden />
      <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-[560px] flex-col border-l border-line bg-surface shadow-2xl" role="dialog" aria-modal="true" data-testid="recipe-drawer">
        <header className="panel-title">
          <div className="min-w-0">
            <h2>{t('recipes.drawerTitle')}</h2>
            <p className="truncate text-xs text-muted">{flow.data?.name ?? ''} · {t('recipes.count', { count: list.length })}</p>
          </div>
          <div className="flex items-center gap-1">
            <Button size="xs" icon={<Upload size={13} />} disabled={readOnly} onClick={() => setImportOpen(true)} data-testid="recipe-import">{t('recipes.import')}</Button>
            <Button size="xs" icon={<Download size={13} />} disabled={list.length === 0} onClick={() => void exportAll()} data-testid="recipe-export-all">{t('recipes.exportAll')}</Button>
            <IconButton size="sm" label={t('common.close')} onClick={onClose} data-testid="recipe-drawer-close"><X size={16} /></IconButton>
          </div>
        </header>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          <section className="rounded-md border border-line bg-surface-muted/50 p-3">
            <BoundRecipeSelect flowId={flowId} recipes={list} disabled={readOnly} testId="drawer-bound" />
            <p className="hint">{t('recipes.boundHint')}</p>
          </section>
          {!readOnly ? (
            <section className="space-y-2 rounded-md border border-line p-3" data-testid="recipe-new">
              <p className="text-xs font-semibold text-heading">{t('recipes.new')}</p>
              <div className="flex items-end gap-1.5">
                <TextInput label={t('teach.recipeName')} className="!h-8" value={newName} onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && void createRecipe()} data-testid="recipe-new-name" />
                <Button size="sm" variant="primary" icon={<Plus size={14} />} loading={create.isPending} onClick={() => void createRecipe()} data-testid="recipe-create">{t('common.create')}</Button>
              </div>
              <label className="flex items-center gap-2 text-xs text-muted">
                <input type="checkbox" className="accent-[var(--brand)]" checked={fromGraph} disabled={teachCount === 0} onChange={(e) => setFromGraph(e.target.checked)} data-testid="recipe-new-from-graph" />
                {t('recipes.fromGraph', { count: teachCount })}
              </label>
            </section>
          ) : null}
          <ul className="space-y-2" data-testid="recipe-list">
            {list.length === 0 ? <li className="rounded-md border border-dashed border-line px-3 py-4 text-center text-xs text-muted">{t('teach.recipeEmpty')}</li> : null}
            {list.map((r) => (
              <RecipeRow
                key={`${r.id}:${r.updated_at}`}
                flowId={flowId}
                recipe={r}
                graph={graph}
                defs={defs}
                readOnly={readOnly}
                expanded={expandedId === r.id}
                onToggle={() => setExpandedId((cur) => (cur === r.id ? null : r.id))}
                onSave={(o) => void saveRecipe(r, o)}
                onExport={() => void exportOne(r)}
                onDuplicate={() => void duplicate(r)}
                onDelete={() => setPendingDelete(r)}
                onBind={() => void bind(r)}
              />
            ))}
          </ul>
        </div>
      </aside>
      {saveCheck.modal}
      <RecipeImportModal open={importOpen} onClose={() => setImportOpen(false)} flowId={flowId} />
      <ConfirmDialog open={pendingDelete !== null} onClose={() => setPendingDelete(null)} onConfirm={() => void doDelete()} title={t('teach.recipeDelete')} message={t('teach.recipeDeleteMessage', { name: pendingDelete?.name ?? '' })} confirmLabel={t('common.delete')} danger loading={remove.isPending} />
    </>
  )
}
