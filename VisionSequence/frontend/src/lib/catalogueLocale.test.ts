/**
 * 目錄翻譯：**顯示的字換成中文，存進資料庫的 kind／key 一定保持英文**。
 * 這正是「設定選項呈現中文、資料庫存英文」的那條規則，所以用測試鎖住。
 */
import { describe, expect, it } from 'vitest'

import { localiseInspectKinds, localiseList } from './catalogueLocale'
import { INSPECT_KINDS } from '@/test/apiMock'

describe('catalogueLocale', () => {
  it('translates inspection display text while preserving kind, roles, fields and option values', () => {
    for (const language of ['zh-Hant', 'zh-Hans'] as const) {
      const result = localiseInspectKinds(INSPECT_KINDS, language)
      expect(result[0].label).not.toBe(INSPECT_KINDS[0].label)
      expect(result[0].kind).toBe('measure_diameter')
      expect(result[0].roles).toEqual(INSPECT_KINDS[0].roles)
      expect(result[0].fields.map((field) => [field.key, field.param, field.role, field.default, field.options.map((option) => option.value)])).toEqual(INSPECT_KINDS[0].fields.map((field) => [field.key, field.param, field.role, field.default, field.options.map((option) => option.value)]))
    }
    expect(INSPECT_KINDS[0].label).toBe('Measure diameter')
  })
  const sourceKinds = [
    { kind: 'capture', label: 'Capture client camera', description: 'The capture client program…', fields: ['client'] },
    { kind: 'folder', label: 'Folder (reads the image files in a loop)', fields: ['path'] },
    { kind: 'gige_plugin', label: 'Plugin: gige_plugin', fields: [] },
  ]

  it('translates the label but never the stored kind', () => {
    const out = localiseList('sourceKinds', sourceKinds, (k) => k.kind, 'zh-Hant')
    expect(out.map((k) => k.kind)).toEqual(['capture', 'folder', 'gige_plugin'])
    expect(out[0].label).toBe('擷取端相機')
    expect(out[1].label).toBe('資料夾（循環讀取影像檔）')
    expect(out[0].description).toContain('擷取端程式')
    // 其他欄位原樣保留
    expect(out[0].fields).toEqual(['client'])
  })

  it('leaves an entry with no translation alone (plugins keep the backend wording)', () => {
    const out = localiseList('sourceKinds', sourceKinds, (k) => k.kind, 'zh-Hans')
    expect(out[2]).toEqual(sourceKinds[2])
  })

  it('returns the English catalogue untouched', () => {
    expect(localiseList('sourceKinds', sourceKinds, (k) => k.kind, 'en')).toEqual(sourceKinds)
  })

  it('translates connection kinds and trainers by the same key', () => {
    const conns = localiseList('connectionKinds', [{ kind: 'modbus_server', label: 'Modbus/TCP server (this machine listens)' }], (k) => k.kind, 'zh-Hant')
    expect(conns[0].kind).toBe('modbus_server')
    expect(conns[0].label).toContain('從站')
    const trainers = localiseList('trainers', [{ kind: 'ai_detect', label: 'Object detection (AI)' }], (t) => t.kind, 'zh-Hans')
    expect(trainers[0].label).toBe('目标检测（AI）')
  })

  it('translates a built-in template by its key, and leaves a custom one alone', () => {
    const items = [
      { id: 'builtin:hole_count', name: 'Hole count', description: 'Grayscale, denoise…' },
      { id: '0f3c-uuid', name: 'My own template', description: 'mine' },
    ]
    const out = localiseList('templates', items, (t) => t.id.replace(/^builtin:/, ''), 'zh-Hant')
    expect(out[0].id).toBe('builtin:hole_count')
    expect(out[0].name).toBe('孔數計數')
    expect(out[1]).toEqual(items[1])
  })
})
