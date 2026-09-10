/** 任務的幾何來源遵守埠語意與循環限制，選取後交給翻譯器建線。 */
import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { GeometrySourceField } from './GeometrySourceField'
import type { FlowGraph, InspectField, ToolPort, ToolTypeDef } from '@/lib/types'

const port = (key: string, extra: Partial<ToolPort> = {}): ToolPort => ({ key, label: key, type: 'any', required: false, multiple: false, tone: 'neutral', ...extra })
const tool = (key: string, inputs: ToolPort[], outputs: ToolPort[]): ToolTypeDef => ({ key, label: key, description: '', category: 'test', category_label: 'Test', icon: 'Box', heavy: false, params: [], inputs, outputs })
const field = { key: 'reference', label: 'Reference geometry', kind: 'json', help_text: 'Select a line or circle.' } as InspectField

it('offers semantic geometry, excludes cycles and returns a source reference', () => {
  const defs = new Map([
    ['shape', tool('shape', [], [port('line', { semantic: 'line' }), port('circle', { semantic: 'circle' }), port('plain')])],
    ['edge_defect', tool('edge_defect', [port('line', { accepts_semantics: ['line'] }), port('circle', { accepts_semantics: ['circle'] })], [])],
  ])
  const graph: FlowGraph = { nodes: [{ id: 'source', type: 'shape' }, { id: 'task_defect', type: 'edge_defect' }, { id: 'later', type: 'shape' }], edges: [{ source: 'task_defect', target: 'later' }] }
  const onChange = vi.fn()
  render(<GeometrySourceField field={field} value={null} graph={graph} nodeId="task_defect" defs={defs} onChange={onChange} />)
  const options = screen.getAllByRole('option')
  expect(options.map((option) => option.textContent)).toEqual(['(none)', 'shape · line', 'shape · circle'])
  fireEvent.change(screen.getByTestId('inspect-geometry-source'), { target: { value: JSON.stringify({ node_id: 'source', port: 'circle', type: 'circle' }) } })
  expect(onChange).toHaveBeenCalledWith({ node_id: 'source', port: 'circle', type: 'circle' })
  fireEvent.change(screen.getByTestId('inspect-geometry-source'), { target: { value: '' } })
  expect(onChange).toHaveBeenLastCalledWith(null)
})
