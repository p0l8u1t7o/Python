/**
 * 側欄（Inspector）：選取步驟的基本設定（名稱、備註、顏色、啟用、出錯時繼續）＋「開啟工具頁」。
 * 完整參數表單在工具頁（ToolPage）。
 */
import { useEffect, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router-dom'
import { SlidersHorizontal } from 'lucide-react'

import { SourcePicker } from '@/components/editor/SourcePicker'
import { Button, Checkbox, Select, TextArea, TextInput } from '@/components/ui'
import { sourcePreviewUrl } from '@/lib/api'
import { useAuth } from '@/providers/AuthProvider'
import { ImagesField } from '@/components/editor/ParamField'
import { dataOutputPorts, nodeProblems, validatePublishName } from '@/lib/graphValidation'
import { outputAliases, withOutputAlias } from '@/lib/nodeInterface'
import { useSources } from '@/lib/queries'
import { localiseDataName } from '@/lib/catalogueLocale'
import type { Language } from '@/i18n'
import type { FlowGraph, GraphEdge, GraphNode, ToolTypeDef } from '@/lib/types'

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

export function Inspector({ flowId, node, definition, edges, graph, defs, onChange, onGraphChange, onDelete }: { flowId: number; node: GraphNode; definition: ToolTypeDef | undefined; edges: GraphEdge[]; graph: FlowGraph; defs: Map<string, ToolTypeDef>; onChange: (patch: Partial<GraphNode>) => void; onGraphChange: (graph: FlowGraph) => string | null; onDelete: () => void }) {
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
      {node.type === 'image_source' ? <SourceSection node={node} onChange={onChange} /> : null}
      {node.type === 'fixed_image' ? <FixedImagesSection node={node} onChange={onChange} /> : null}
      {isNote ? null : <SourcePicker graph={graph} node={node} definition={definition} defs={defs} onGraphChange={onGraphChange} />}
      <TextInput label={t('editor.nodeName')} value={node.label ?? ''} placeholder={definition?.label} hint={isNote ? undefined : t('editor.nodeNameHint')} onChange={(e) => onChange({ label: e.target.value })} />
      <TextArea label={t('editor.nodeNote')} rows={isNote ? 5 : 2} value={node.description ?? ''} onChange={(e) => onChange({ description: e.target.value })} />
      <ColorField label={t('editor.nodeColor')} clearLabel={t('editor.nodeColorReset')} value={node.color ?? ''} onChange={(color) => onChange({ color })} />

      {isNote ? null : (
        <>
          <Checkbox label={t('editor.nodeEnabled')} hint={t('editor.nodeEnabledHint')} checked={node.enabled !== false} onChange={(enabled) => onChange({ enabled })} />
          <Checkbox label={t('editor.continueOnError')} hint={t('editor.continueOnErrorHint')} checked={node.continue_on_error === true} onChange={(continue_on_error) => onChange({ continue_on_error })} />
          <PublishedOutputsSection node={node} definition={definition} onChange={onChange} />

          {problems.length ? (
            <p className="rounded-lg bg-warning-soft px-3 py-2 text-xs text-warning">{t('editor.problemsOnNode', { count: problems.length })}</p>
          ) : null}

          {definition ? (
            <div className="border-t border-line pt-3 text-[11px] text-muted">
              <p>
                <span className="font-medium">{t('editor.inputs')}: </span>
                {definition.inputs.map((p) => `${p.label}(${p.type}${p.required ? '' : '?'})`).join(', ') || '—'}
              </p>
              <p className="mt-0.5">
                <span className="font-medium">{t('editor.outputs')}: </span>
                {definition.outputs.map((p) => `${p.label}(${p.type})`).join(', ') || '—'}
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

/** 固定影像步驟：直接在檢視器上傳／移除圖片（與工具頁的 images 參數同一份值）。 */
function PublishedOutputsSection({ node, definition, onChange }: { node: GraphNode; definition: ToolTypeDef | undefined; onChange: (patch: Partial<GraphNode>) => void }) {
  const { t } = useTranslation()
  const ports = useMemo(() => dataOutputPorts(definition), [definition])
  const published = useMemo(() => outputAliases(node), [node])
  const [draft, setDraft] = useState<Record<string, string>>({})

  useEffect(() => {
    setDraft(Object.fromEntries(ports.map((port) => [port.key, published[port.key] ?? ''])))
  }, [node.id, ports, published])

  if (!definition) return null

  const update = (key: string, value: string) => {
    setDraft((current) => ({ ...current, [key]: value }))
    if (!validatePublishName(value)) return

    onChange(withOutputAlias(node, key, value))
  }

  return (
    <div className="space-y-2 rounded-md border border-line bg-surface p-2" data-testid="published-outputs">
      <p className="text-xs font-semibold text-heading">{t('editor.publishedOutputs.title')}</p>
      {ports.length ? ports.map((port) => {
        const value = draft[port.key] ?? published[port.key] ?? ''
        const invalid = !validatePublishName(value)
        return (
          <TextInput
            key={port.key}
            label={port.label || port.key}
            value={value}
            placeholder={t('editor.publishedOutputs.placeholder')}
            className="font-mono"
            error={invalid ? t('editor.publishedOutputs.invalidName') : undefined}
            onChange={(event) => update(port.key, event.target.value)}
            data-testid={`publish-output-${port.key}`}
          />
        )
      }) : <p className="text-[11px] text-muted">{t('editor.publishedOutputs.empty')}</p>}
    </div>
  )
}

function FixedImagesSection({ node, onChange }: { node: GraphNode; onChange: (patch: Partial<GraphNode>) => void }) {
  const { t } = useTranslation()
  const auth = useAuth()
  return (
    <div className="rounded-md border border-line bg-surface p-2" data-testid="inspector-fixed-images">
      <ImagesField label={t('editor.picturesSection')} value={node.params?.images} readOnly={!auth.isEngineer} onChange={(images) => onChange({ params: { ...(node.params ?? {}), images } })} />
    </div>
  )
}

/** 取像步驟：直接在檢視器選來源並看預覽縮圖，不必進工具頁或來源頁。 */
function SourceSection({ node, onChange }: { node: GraphNode; onChange: (patch: Partial<GraphNode>) => void }) {
  const { t, i18n } = useTranslation()
  const sources = useSources()
  const items = sources.data?.items ?? []
  const id = Number(node.params?.source_id ?? 0) || 0
  const current = items.find((s) => s.id === id)
  return (
    <div className="space-y-2 rounded-md border border-line bg-surface p-2" data-testid="inspector-source">
      <Select
        label={t('editor.sourceSection')}
        value={id ? String(id) : ''}
        options={[{ value: '', label: t('editor.noSourcePick') }, ...items.map((s) => ({ value: String(s.id), label: localiseDataName(s.name, i18n.language as Language) }))]}
        onChange={(e) => {
          const next = Number(e.target.value) || 0
          const params = { ...(node.params ?? {}) }
          if (next) params.source_id = next
          else delete params.source_id
          onChange({ params })
        }}
        data-testid="inspector-source-select"
      />
      {id ? (
        <img
          key={id}
          src={sourcePreviewUrl(id, 480)}
          alt={current?.name ?? ''}
          className="max-h-40 w-full rounded border border-line object-contain"
          data-testid="inspector-source-preview"
          onError={(e) => { e.currentTarget.style.display = 'none' }}
        />
      ) : null}
      {current?.kind === 'capture' && current.status?.connected === false ? (
        <p className="text-[11px] text-warning" data-testid="inspector-capture-offline">{t('editor.captureOffline', { name: String(current.config?.client ?? '') })}</p>
      ) : null}
      <p className="text-[11px] text-muted">
        {id ? t('editor.sourcePreviewHint') : t('editor.noSourceBanner')} · <Link to="/sources" className="underline">{t('editor.manageSources')}</Link>
      </p>
    </div>
  )
}
