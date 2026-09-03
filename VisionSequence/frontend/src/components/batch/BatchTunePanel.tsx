/** 調參面板：工作圖的現場調機參數（teach）分組編輯 → 重新執行同一影像集；滿意後寫回流程、存為配方或帶回編輯器。 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { ArrowLeft, BookmarkPlus, Play, RotateCcw, Save, Wand2 } from 'lucide-react'

import { ParamField, type InspectorActions } from '@/components/editor/ParamField'
import { Badge, Button, TextInput } from '@/components/ui'
import { paramDiff } from '@/lib/batch'
import { teachGroupsOf } from '@/lib/teachGroups'
import type { FlowGraph, ToolTypeDef } from '@/lib/types'

const NO_ACTIONS: InspectorActions = { roiEditingKey: null, setRoiEditing: () => undefined, templateFromImage: () => undefined, templateKey: null, hasImage: false }

export function BatchTunePanel({ graph, baseGraph, defs, canEditFlow, sourceRunId, onChange, onRun, onSaveFlow, onSaveRecipe, onReset, onToEditor, busy, hasLabels = false, onAutotune }: {
  graph: FlowGraph | null
  baseGraph: FlowGraph | null
  defs: Map<string, ToolTypeDef>
  canEditFlow: boolean
  sourceRunId: number | null
  onChange: (graph: FlowGraph) => void
  onRun: () => void
  onSaveFlow: () => void
  onSaveRecipe: (name: string) => void
  onReset: () => void
  onToEditor: () => void
  busy: boolean
  hasLabels?: boolean
  onAutotune?: () => void
}) {
  const { t } = useTranslation()
  const [recipeName, setRecipeName] = useState('')
  const groups = useMemo(() => teachGroupsOf(graph, defs), [graph, defs])
  const diff = useMemo(() => (graph && baseGraph ? paramDiff(baseGraph, graph) : []), [graph, baseGraph])
  if (!graph) return <p className="text-xs text-muted">{t('batchPage.tune.noGraph')}</p>

  function setParam(nodeId: string, key: string, value: unknown) {
    if (!graph) return
    onChange({ ...graph, nodes: graph.nodes.map((n) => (n.id === nodeId ? { ...n, params: { ...(n.params ?? {}), [key]: value } } : n)) })
  }

  return (
    <div className="space-y-3" data-testid="batch-tune">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <span className="text-muted">{t('batchPage.tune.hint')}</span>
        {sourceRunId !== null ? <Badge>{t('batchPage.tune.fromRun', { id: sourceRunId })}</Badge> : null}
        <Badge tone={diff.length ? 'brand' : 'neutral'}>{t('batchPage.tune.changes', { count: diff.length })}</Badge>
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="primary" icon={<Play size={14} />} loading={busy} onClick={onRun} data-testid="batch-tune-run">{t('batchPage.tune.run')}</Button>
        {onAutotune ? <Button size="sm" icon={<Wand2 size={14} />} disabled={!hasLabels || busy} title={hasLabels ? t('batchPage.ai.autotuneHint') : t('batchPage.ai.noLabels')} onClick={onAutotune} data-testid="batch-tune-autotune">{t('batchPage.ai.autotune')}</Button> : null}
        <Button size="sm" icon={<RotateCcw size={14} />} disabled={!diff.length} onClick={onReset}>{t('batchPage.tune.reset')}</Button>
        <Button size="sm" icon={<ArrowLeft size={14} />} onClick={onToEditor}>{t('batchPage.tune.toEditor')}</Button>
        <Button size="sm" icon={<Save size={14} />} disabled={!canEditFlow || !diff.length} title={canEditFlow ? undefined : t('golden.readOnly')} onClick={onSaveFlow} data-testid="batch-tune-save-flow">{t('batchPage.tune.saveFlow')}</Button>
        <span className="flex items-center gap-1">
          <TextInput className="!w-36 !py-1 text-xs" placeholder={t('batchPage.tune.recipeName')} value={recipeName} onChange={(e) => setRecipeName(e.target.value)} />
          <Button size="sm" icon={<BookmarkPlus size={14} />} disabled={!canEditFlow || !diff.length || !recipeName.trim()} onClick={() => { onSaveRecipe(recipeName.trim()); setRecipeName('') }} data-testid="batch-tune-save-recipe">{t('batchPage.tune.saveRecipe')}</Button>
        </span>
      </div>
      {groups.length === 0 ? <p className="text-xs text-muted">{t('batchPage.tune.noTeach')}</p> : null}
      <div className="grid gap-3 lg:grid-cols-2">
        {groups.map((g) => (
          <div key={g.node.id} className="rounded-lg border border-line p-3" data-testid="batch-tune-group">
            <p className="mb-2 text-xs font-semibold">{g.node.label || g.def.label} <span className="font-mono text-[10px] text-subtle">{g.node.id} · {g.def.key}</span></p>
            <div className="space-y-2">
              {g.params.map((p) => {
                const changed = diff.some((d) => d.node === g.node.id && d.key === p.key)
                return (
                  <div key={p.key} className={changed ? 'rounded border-l-2 border-brand pl-2' : ''}>
                    <ParamField param={p} value={g.node.params?.[p.key] ?? p.default} onChange={(v) => setParam(g.node.id, p.key, v)} actions={NO_ACTIONS} />
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
