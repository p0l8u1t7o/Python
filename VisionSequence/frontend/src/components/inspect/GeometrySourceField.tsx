/** 幾何來源欄位只選真實埠；候選過濾沿用編輯器的型別與循環檢查。 */
import { useTranslation } from 'react-i18next'
import { Select } from '@/components/ui'
import { sourceCandidates } from '@/lib/sourceCandidates'
import type { FlowGraph, InspectField, ToolTypeDef } from '@/lib/types'

interface GeometrySource { node_id: string; port: string; type: string }
interface Props {
  field: InspectField
  value: unknown
  graph: FlowGraph
  nodeId?: string
  defs: Map<string, ToolTypeDef>
  onChange: (value: GeometrySource | null) => void
}

export function GeometrySourceField({ field, value, graph, nodeId, defs, onChange }: Props) {
  const { t } = useTranslation()
  const target = nodeId ?? '__inspect_geometry_preview__'
  const candidateGraph = nodeId ? graph : { ...graph, nodes: [...graph.nodes, { id: target, type: 'edge_defect' }] }
  const choices = ['line', 'circle'].flatMap((type) => sourceCandidates(candidateGraph, target, type, defs)
    .filter((item) => defs.get(graph.nodes.find((node) => node.id === item.nodeId)?.type ?? '')?.outputs.find((port) => port.key === item.portKey)?.semantic === type)
    .map((item) => ({ value: JSON.stringify({ node_id: item.nodeId, port: item.portKey, type }), label: `${item.nodeLabel} · ${item.portLabel}` })))
  const selected = value && typeof value === 'object' ? value as GeometrySource : null
  const selectedValue = selected ? JSON.stringify({ node_id: selected.node_id, port: selected.port, type: selected.type }) : ''
  return <div>
    <Select label={field.label} value={selectedValue} data-testid="inspect-geometry-source"
      options={[{ value: '', label: t('common.none') }, ...(selected && !choices.some((item) => item.value === selectedValue) ? [{ value: selectedValue, label: `${selected.node_id} · ${selected.port}`, disabled: true }] : []), ...choices]}
      onChange={(event) => onChange(event.target.value ? JSON.parse(event.target.value) as GeometrySource : null)} />
    <p className="mt-1 text-xs text-muted">{field.help_text}</p>
  </div>
}
