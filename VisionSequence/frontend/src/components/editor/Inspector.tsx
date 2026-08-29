/**
 * 側欄（Inspector）：選取步驟的基本設定（名稱、備註、顏色、啟用、出錯時繼續）＋「開啟工具頁」。
 * 完整參數表單在工具頁（ToolPage）。
 */
import { useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { SlidersHorizontal } from 'lucide-react'

import { Button, Checkbox, TextArea, TextInput } from '@/components/ui'
import { nodeProblems } from '@/lib/graphValidation'
import type { GraphEdge, GraphNode, ToolTypeDef } from '@/lib/types'

const NODE_COLORS = ['#0f766e', '#1d4ed8', '#7c3aed', '#b45309', '#be123c', '#0891b2', '#4d7c0f', '#334155']

function ColorField({ value, onChange, label, clearLabel }: { value: string; onChange: (color: string) => void; label: string; clearLabel: string }) {
  return (
    <div>
      <p className="label">{label}</p>
      <div className="flex flex-wrap items-center gap-1.5">
        {NODE_COLORS.map((color) => (
          <button key={color} type="button" aria-label={color} onClick={() => onChange(color)} className={`size-5 rounded-full border ${value === color ? 'ring-2 ring-brand ring-offset-1' : 'border-line'}`} style={{ background: color }} />
        ))}
        <input type="color" value={/^#[0-9a-fA-F]{6}$/.test(value) ? value : '#0f766e'} onChange={(e) => onChange(e.target.value)} className="size-6 cursor-pointer rounded border border-line bg-transparent p-0" title={label} />
        {value ? <button type="button" onClick={() => onChange('')} className="text-[11px] text-muted hover:underline">{clearLabel}</button> : null}
      </div>
    </div>
  )
}

export function Inspector({ flowId, node, definition, edges, onChange, onDelete }: { flowId: number; node: GraphNode; definition: ToolTypeDef | undefined; edges: GraphEdge[]; onChange: (patch: Partial<GraphNode>) => void; onDelete: () => void }) {
  const { t } = useTranslation()
  const isNote = node.type === 'note'
  const problems = useMemo(() => nodeProblems(node, definition, edges), [node, definition, edges])
  const toolPage = `/flows/${flowId}/tools/${encodeURIComponent(node.id)}`

  return (
    <div className="space-y-3 p-3" data-testid="inspector">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 text-sm font-semibold">
            <span className="truncate">{node.label || definition?.label || node.type}</span>
            {isNote ? null : (
              <Link to={toolPage} className="btn-icon !p-1 text-brand" title={t('editor.openToolPage')} aria-label={t('editor.openToolPage')} data-testid="open-tool-page-icon">
                <SlidersHorizontal size={14} />
              </Link>
            )}
          </p>
          {definition?.description ? <p className="mt-0.5 text-xs text-muted">{definition.description}</p> : null}
        </div>
      </div>
      {isNote ? null : (
        <Link to={toolPage} className="block" data-testid="open-tool-page">
          <Button variant="primary" size="sm" className="w-full" icon={<SlidersHorizontal size={14} />}>
            {t('editor.openToolPage')}
          </Button>
        </Link>
      )}
      <TextInput label={t('editor.nodeName')} value={node.label ?? ''} placeholder={definition?.label} hint={isNote ? undefined : t('editor.nodeNameHint')} onChange={(e) => onChange({ label: e.target.value })} />
      <TextArea label={t('editor.nodeNote')} rows={isNote ? 5 : 2} value={node.description ?? ''} onChange={(e) => onChange({ description: e.target.value })} />
      <ColorField label={t('editor.nodeColor')} clearLabel={t('editor.nodeColorReset')} value={node.color ?? ''} onChange={(color) => onChange({ color })} />

      {isNote ? null : (
        <>
          <Checkbox label={t('editor.nodeEnabled')} hint={t('editor.nodeEnabledHint')} checked={node.enabled !== false} onChange={(enabled) => onChange({ enabled })} />
          <Checkbox label={t('editor.continueOnError')} hint={t('editor.continueOnErrorHint')} checked={node.continue_on_error === true} onChange={(continue_on_error) => onChange({ continue_on_error })} />

          {problems.length ? (
            <p className="rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">{t('editor.problemsOnNode', { count: problems.length })}</p>
          ) : null}

          {definition ? (
            <div className="border-t border-line pt-3 text-[11px] text-muted">
              <p>
                <span className="font-medium">{t('editor.inputs')}：</span>
                {definition.inputs.map((p) => `${p.label}(${p.type}${p.required ? '' : '?'})`).join('、') || '—'}
              </p>
              <p className="mt-0.5">
                <span className="font-medium">{t('editor.outputs')}：</span>
                {definition.outputs.map((p) => `${p.label}(${p.type})`).join('、') || '—'}
              </p>
            </div>
          ) : null}
        </>
      )}

      <div className="border-t border-line pt-3">
        <p className="mb-2 font-mono text-[11px] text-muted">id: {node.id}</p>
        <button type="button" onClick={onDelete} className="text-xs text-critical hover:underline">{t('editor.deleteNode')}</button>
      </div>
    </div>
  )
}
