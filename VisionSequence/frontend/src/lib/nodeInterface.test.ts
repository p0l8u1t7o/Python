/** node.interface 純函式：具名輸出名稱、參數訂閱埠、空介面不留物件（與後端 tools/base.py 同語意）。 */
import { describe, expect, it } from 'vitest'

import { exposedParamKeys, nodeInterface, outputAliases, withOutputAlias, withParamExposed } from './nodeInterface'

describe('nodeInterface', () => {
  it('reads aliases and exposed params tolerantly', () => {
    const node = { interface: { outputs: [{ key: 'value', alias: ' diameter ' }, { key: 'image', exposed: false }, { key: '' }], inputs: [{ key: 'param:threshold' }, { key: 'param:hidden', exposed: false }, { key: 'image', exposed: false }] } }
    expect(outputAliases(node)).toEqual({ value: 'diameter' })
    expect(exposedParamKeys(node)).toEqual(['threshold'])
    expect(nodeInterface(node).outputs).toHaveLength(2)
    expect(nodeInterface({ interface: undefined })).toEqual({ inputs: [], outputs: [], params: [] })
  })

  it('sets and clears an output alias without leaving empty objects behind', () => {
    const set = withOutputAlias({ interface: undefined }, 'value', 'diameter')
    expect(set.interface).toEqual({ outputs: [{ key: 'value', alias: 'diameter' }] })
    const kept = withOutputAlias({ interface: { outputs: [{ key: 'value', alias: 'diameter', exposed: true }] } }, 'value', '')
    expect(kept.interface).toEqual({ outputs: [{ key: 'value', exposed: true }] })
    const cleared = withOutputAlias({ interface: set.interface }, 'value', '   ')
    expect(cleared.interface).toBeUndefined()
  })

  it('exposes and hides parameter ports', () => {
    const on = withParamExposed({ interface: undefined }, 'threshold', true)
    expect(on.interface).toEqual({ inputs: [{ key: 'param:threshold', exposed: true }] })
    expect(exposedParamKeys(on)).toEqual(['threshold'])
    const off = withParamExposed(on, 'threshold', false)
    expect(off.interface).toBeUndefined()
  })
})
