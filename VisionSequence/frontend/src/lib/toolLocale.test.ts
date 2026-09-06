/**
 * 工具目錄翻譯：分類名稱與隱含埠每個工具都有，沒有字典的工具（外掛）也要翻到；
 * 訓練方式的超參數、分組與選項也要跟著語言走（截圖回報的英文殘留）。
 */
import { describe, expect, it } from 'vitest'

import { localiseTrainers } from './catalogueLocale'
import { localiseCatalogue } from './toolLocale'
import type { DlTrainerDef, ToolCatalogue } from './types'

const PORT = { type: 'image', required: false, multiple: false, tone: 'neutral' } as const

const catalogue = {
  categories: [{ key: 'source', label: 'Image source' }],
  items: [
    {
      key: 'image_source', label: 'Image source', description: '', category: 'source', category_label: 'Image source', icon: 'Camera', heavy: false, params: [],
      inputs: [{ key: '_image', label: 'Image (pass-through)', ...PORT, implicit: true }],
      outputs: [{ key: 'image', label: 'Image', ...PORT }, { key: '_overlays', label: 'Overlays', ...PORT, type: 'list', implicit: true }],
    },
    {
      // 字典裡沒有的工具（外掛）：分類與隱含埠照翻，它自己的埠維持後端英文
      key: 'my_plugin_tool', label: 'My plugin tool', description: '', category: 'detect', category_label: 'Detect / identify', icon: 'Box', heavy: false, params: [],
      inputs: [{ key: '_image', label: 'Image (pass-through)', ...PORT, implicit: true }],
      outputs: [{ key: 'ratio', label: 'Ratio', ...PORT, type: 'number' }],
    },
  ],
} as unknown as ToolCatalogue

describe('toolLocale', () => {
  it('translates every tool’s category label, not only the category list', () => {
    const out = localiseCatalogue(catalogue, 'zh-Hant')
    expect(out.categories[0].label).toBe('影像來源')
    expect(out.items[0].category_label).toBe('影像來源')
    expect(out.items[1].category_label).toBe('檢測 / 識別')  // 外掛沒有字典，分類照樣翻
  })

  it('translates the implicit ports shared by every tool, plugins included', () => {
    const out = localiseCatalogue(catalogue, 'zh-Hant')
    expect(out.items[0].inputs[0].label).toBe('影像（直通）')
    expect(out.items[0].outputs[1].label).toBe('標記')
    expect(out.items[1].inputs[0].label).toBe('影像（直通）')
    expect(out.items[1].outputs[0].label).toBe('Ratio')  // 外掛自己的埠維持後端英文
    expect(out.items[0].key).toBe('image_source')
  })

  it('leaves English untouched', () => {
    expect(localiseCatalogue(catalogue, 'en')).toBe(catalogue)
  })
})

describe('localiseTrainers', () => {
  const trainers = [
    {
      kind: 'mlp_classify', label: 'Image classification (MLP)', description: '', label_mode: 'classes', tool_key: 'dl_classify', devices: ['cpu'], min_per_class: 2,
      params: [
        { key: 'input_size', label: 'Input size', kind: 'select', required: false, default: 64, help_text: '', options: [{ value: 64, label: '64x64 (recommended)' }], unit: '', minimum: null, maximum: null, step: null, visible_when: null, shapes: [], accept: '', group: '', teach: false },
        { key: 'epochs', label: 'Epochs', kind: 'number', required: false, default: 300, help_text: '', options: [], unit: '', minimum: 10, maximum: 5000, step: null, visible_when: null, shapes: [], accept: '', group: 'Advanced', teach: false },
      ],
    },
    {
      kind: 'ai_detect', label: 'Object detection (AI)', description: '', label_mode: 'shapes', tool_key: 'ai_detect', devices: ['cuda'], min_per_class: 2,
      params: [
        { key: 'mosaic', label: 'Mosaic augmentation', kind: 'number', required: false, default: 1, help_text: 'Tiles four samples…', options: [], unit: '', minimum: 0, maximum: 1, step: 0.1, visible_when: null, shapes: [], accept: '', group: 'Augment', teach: false },
        { key: 'custom_from_plugin', label: 'Custom', kind: 'number', required: false, default: 1, help_text: '', options: [], unit: '', minimum: 0, maximum: 1, step: 1, visible_when: null, shapes: [], accept: '', group: 'Advanced', teach: false },
      ],
    },
  ] as unknown as DlTrainerDef[]

  it('translates parameter labels, help, options and group names', () => {
    const [mlp, yolo] = localiseTrainers(trainers, 'zh-Hant')
    expect(mlp.label).toBe('影像分類（MLP）')
    expect(mlp.params[0].label).toBe('輸入尺寸')
    expect(mlp.params[0].options[0].label).toBe('64x64（建議）')
    expect(mlp.params[0].options[0].value).toBe(64)  // 值不動
    expect(mlp.params[1].group).toBe('進階')
    // 神經網路四種共用一份參數字典
    expect(yolo.params[0].label).toBe('Mosaic 增強')
    expect(yolo.params[0].help_text).toContain('四張')
    expect(yolo.params[0].group).toBe('資料增強')
    // 沒有對照的參數：名稱維持英文，但分組名稱照翻
    expect(yolo.params[1].label).toBe('Custom')
    expect(yolo.params[1].group).toBe('進階')
  })

  it('leaves English untouched', () => {
    expect(localiseTrainers(trainers, 'en')).toBe(trainers)
  })
})
