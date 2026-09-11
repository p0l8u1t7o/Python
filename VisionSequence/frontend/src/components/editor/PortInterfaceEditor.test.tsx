/** 工具頁的埠編輯區：勾選顯示／隱藏、已接線鎖住、上下移動寫 order、自動排序、還原預設、具名輸出名稱只在合法時寫回。 */
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { PortInterfaceEditor } from './PortInterfaceEditor'
import type { GraphEdge, GraphNode, ToolPort, ToolTypeDef } from '@/lib/types'

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k: string) => k }) }))

function port(key: string, type: ToolPort['type'] = 'number', extra: Partial<ToolPort> = {}): ToolPort {
  return { key, label: key, type, required: false, multiple: false, tone: 'neutral', ...extra }
}

const def: ToolTypeDef = {
  key: 'measure', label: 'Measure', description: '', category: 'measure', category_label: 'Measure', icon: 'Ruler', heavy: false, params: [],
  inputs: [port('image', 'image', { required: true, primary: true }), port('region', 'region', { required: true }), port('ref')],
  outputs: [port('image', 'image', { primary: true }), port('value'), port('width'), port('ok', 'flow')],
}
const edges: GraphEdge[] = [{ source: 'src', source_handle: 'image', target: 'm', target_handle: 'image' }, { source: 'm', source_handle: 'value', target: 'd', target_handle: 'v' }]
const nodes: GraphNode[] = [{ id: 'src', type: 'x', params: {}, position: { x: 0, y: 0 } }, { id: 'd', type: 'x', params: {}, position: { x: 300, y: 0 } }]

function show(node: GraphNode, readOnly = false) {
  const onChange = vi.fn()
  render(<PortInterfaceEditor node={node} definition={def} edges={edges} nodes={[...nodes, node]} readOnly={readOnly} onChange={onChange} />)
  return onChange
}

describe('PortInterfaceEditor', () => {
  it('locks connected ports and writes exposed flags for the others', () => {
    const node: GraphNode = { id: 'm', type: 'measure', params: {} }
    const onChange = show(node)
    expect(screen.getByTestId('port-visible-in-image')).toBeDisabled()
    expect(screen.getByTestId('port-visible-in-image')).toHaveAttribute('title', 'editor.ports.connectedLocked')
    expect(screen.getByTestId('port-row-out-width')).toHaveAttribute('data-visible', 'false')
    fireEvent.click(screen.getByTestId('port-visible-out-width'))
    expect(onChange).toHaveBeenLastCalledWith({ interface: { outputs: [{ key: 'width', exposed: true }] } })
    fireEvent.click(screen.getByTestId('port-visible-in-region'))
    expect(onChange).toHaveBeenLastCalledWith({ interface: { inputs: [{ key: 'region', exposed: false }] } })
  })

  it('warns about hidden required inputs and reorders with the arrows', () => {
    const node: GraphNode = { id: 'm', type: 'measure', params: {}, interface: { inputs: [{ key: 'region', exposed: false }] } }
    const onChange = show(node)
    expect(screen.getByTestId('port-hidden-required')).toBeInTheDocument()
    expect(screen.getByTestId('port-up-out-image')).toBeDisabled()
    fireEvent.click(screen.getByTestId('port-down-out-image'))
    expect(onChange).toHaveBeenLastCalledWith({ interface: { inputs: [{ key: 'region', exposed: false }], outputs: [{ key: 'value', order: 0 }, { key: 'image', order: 1 }, { key: 'width', order: 2 }, { key: 'ok', order: 3 }] } })
    expect(screen.getByTestId('port-reset-in')).not.toBeDisabled()
    fireEvent.click(screen.getByTestId('port-reset-in'))
    expect(onChange).toHaveBeenLastCalledWith({ interface: undefined })
  })

  it('auto-sorts by the connected peers and only commits valid published names', () => {
    const node: GraphNode = { id: 'm', type: 'measure', params: {} }
    const onChange = show(node)
    fireEvent.click(screen.getByTestId('port-autosort-out'))
    expect(onChange).toHaveBeenLastCalledWith({ interface: { outputs: [{ key: 'value', order: 0 }, { key: 'image', order: 1 }, { key: 'width', order: 2 }, { key: 'ok', order: 3 }] } })
    expect(screen.queryByTestId('port-alias-ok')).toBeNull()
    const alias = screen.getByTestId('port-alias-width')
    fireEvent.change(alias, { target: { value: '1bad' } })
    expect(alias).toHaveAttribute('aria-invalid', 'true')
    expect(onChange).toHaveBeenCalledTimes(1)
    fireEvent.change(alias, { target: { value: 'part_width' } })
    expect(onChange).toHaveBeenLastCalledWith({ interface: { outputs: [{ key: 'width', alias: 'part_width' }] } })
  })

  it('disables everything when read only', () => {
    show({ id: 'm', type: 'measure', params: {} }, true)
    expect(screen.getByTestId('port-visible-out-width')).toBeDisabled()
    expect(screen.getByTestId('port-alias-width')).toBeDisabled()
    expect(screen.getByTestId('port-autosort-out')).toBeDisabled()
  })
})
