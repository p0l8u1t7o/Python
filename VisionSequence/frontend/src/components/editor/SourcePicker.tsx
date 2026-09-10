import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { X } from 'lucide-react'

import { addInputSource, removeInputSource, replaceInputSource } from '@/components/editor/graphMapping'
import { Select } from '@/components/ui'
import { sourceCandidates, type SourceCandidate } from '@/lib/sourceCandidates'
import type { FlowGraph, GraphEdge, GraphNode, ToolPort, ToolTypeDef } from '@/lib/types'

interface SourcePickerProps {
  graph: FlowGraph
  node: GraphNode
  definition: ToolTypeDef | undefined
  defs: Map<string, ToolTypeDef>
  onGraphChange: (graph: FlowGraph) => string | null
}

function optionValue(candidate: Pick<SourceCandidate, 'nodeId' | 'portKey'>): string {
  return `${candidate.nodeId}\u0000${candidate.portKey}`
}

function parseOption(value: string): { nodeId: string; portKey: string } | null {
  const [nodeId, portKey] = value.split('\u0000')
  return nodeId && portKey ? { nodeId, portKey } : null
}

function edgeLabel(edge: GraphEdge, graph: FlowGraph, defs: Map<string, ToolTypeDef>): string {
  const node = graph.nodes.find((item) => item.id === edge.source)
  const def = node ? defs.get(node.type) : undefined
  const port = def?.outputs.find((item) => item.key === (edge.source_handle ?? ''))
  return `${node?.label || def?.label || edge.source} · ${port?.label || edge.source_handle || ''}`
}

function portTypeLabel(port: ToolPort): string {
  return port.multiple ? `${port.type}[]` : port.type
}

export function SourcePicker({ graph, node, definition, defs, onGraphChange }: SourcePickerProps) {
  const { t } = useTranslation()
  const [error, setError] = useState<string | null>(null)
  const inputPorts = useMemo(() => (definition?.inputs ?? []).filter((port) => port.type !== 'flow'), [definition])

  if (!definition || inputPorts.length === 0) return null

  const apply = (next: FlowGraph) => {
    const message = onGraphChange(next)
    setError(message)
  }

  return (
    <div className="space-y-2 rounded-md border border-line bg-surface p-2" data-testid="source-picker">
      <p className="text-xs font-semibold text-heading">{t('editor.sourcePicker.title')}</p>
      {inputPorts.map((port) => {
        const incoming = (graph.edges ?? []).filter((edge) => edge.target === node.id && (edge.target_handle ?? '') === port.key)
        const candidates = sourceCandidates(graph, node.id, port.key, defs)
        const options = candidates.map((candidate) => ({ value: optionValue(candidate), label: `${candidate.nodeLabel} · ${candidate.portLabel}` }))
        const current = incoming[0]
        const currentValue = current ? optionValue({ nodeId: current.source, portKey: current.source_handle ?? '' }) : ''
        const currentInOptions = current ? options.some((option) => option.value === currentValue) : true

        if (port.multiple) {
          return (
            <div key={port.key} className="space-y-1.5 rounded border border-line/70 p-2" data-testid={`source-picker-port-${port.key}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs font-medium text-content">{port.label || port.key}</span>
                <span className="font-mono text-[10px] text-subtle">{portTypeLabel(port)}</span>
              </div>
              {incoming.length ? (
                <div className="space-y-1">
                  {incoming.map((edge) => (
                    <div key={`${edge.source}:${edge.source_handle ?? ''}`} className="flex items-center justify-between gap-2 rounded bg-surface-muted px-2 py-1 text-xs">
                      <span className="min-w-0 truncate">{edgeLabel(edge, graph, defs)}</span>
                      <button
                        type="button"
                        className="btn-icon !size-6 !p-1 text-muted hover:text-critical"
                        title={t('editor.sourcePicker.remove')}
                        aria-label={t('editor.sourcePicker.remove')}
                        onClick={() => apply(removeInputSource(graph, node.id, port.key, { nodeId: edge.source, portKey: edge.source_handle ?? '' }))}
                      >
                        <X size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              ) : <p className="text-[11px] text-muted">{t('editor.sourcePicker.unselected')}</p>}
              <Select
                aria-label={t('editor.sourcePicker.add')}
                value=""
                options={[{ value: '', label: candidates.length ? t('editor.sourcePicker.add') : t('editor.sourcePicker.noCandidates'), disabled: true }, ...options]}
                disabled={candidates.length === 0}
                onChange={(event) => {
                  const picked = parseOption(event.target.value)
                  if (picked) apply(addInputSource(graph, node.id, port.key, picked))
                }}
                data-testid={`source-picker-add-${port.key}`}
              />
            </div>
          )
        }

        const singleOptions = [
          { value: '', label: t('editor.sourcePicker.unselected') },
          ...(!currentInOptions && current ? [{ value: currentValue, label: edgeLabel(current, graph, defs), disabled: true }] : []),
          ...options,
        ]
        return (
          <div key={port.key} className="space-y-1 rounded border border-line/70 p-2" data-testid={`source-picker-port-${port.key}`}>
            <Select
              label={<span className="flex items-center justify-between gap-2"><span>{port.label || port.key}</span><span className="font-mono text-[10px] text-subtle">{portTypeLabel(port)}</span></span>}
              value={currentValue}
              options={singleOptions}
              onChange={(event) => {
                const picked = parseOption(event.target.value)
                apply(replaceInputSource(graph, node.id, port.key, picked))
              }}
              data-testid={`source-picker-select-${port.key}`}
            />
          </div>
        )
      })}
      {error ? <p className="rounded bg-warning-soft px-2 py-1 text-[11px] text-warning" data-testid="source-picker-error">{error}</p> : null}
    </div>
  )
}
