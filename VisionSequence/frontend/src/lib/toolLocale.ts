/**
 * Translating the tool catalogue.
 *
 * The backend catalogue is English and is the source of truth. For a Chinese interface we overlay a
 * dictionary here — one place, so every screen that shows a tool name, parameter, option or port
 * gets the translation without knowing about it. A tool with no entry (a folder plugin, say) keeps
 * whatever wording the backend sent, which is exactly what a plugin author would expect.
 */
import zhHans from '@/i18n/locales/tools.zh-Hans'
import zhHant from '@/i18n/locales/tools.zh-Hant'
import type { Language } from '@/i18n'
import type { ToolCatalogue } from '@/lib/types'

interface ToolText {
  label?: string
  description?: string
  params?: Record<string, { label?: string; help?: string; group?: string; options?: Record<string, string> }>
  ports?: Record<string, string>
}

const DICTS: Partial<Record<Language, Record<string, ToolText>>> = {
  'zh-Hant': zhHant as Record<string, ToolText>,
  'zh-Hans': zhHans as Record<string, ToolText>,
}

/** Category labels are short enough to keep beside the dictionary. */
const CATEGORIES: Partial<Record<Language, Record<string, string>>> = {
  'zh-Hant': { source: '影像來源', preprocess: '影像前處理', locate: '定位', measure: '量測', detect: '檢測 / 識別', dl: '深度學習', logic: '邏輯', output: '輸出', decoration: '註解' },
  'zh-Hans': { source: '图像来源', preprocess: '图像前处理', locate: '定位', measure: '测量', detect: '检测 / 识别', dl: '深度学习', logic: '逻辑', output: '输出', decoration: '注释' },
}

/** 隱含埠每個工具都有一份，翻譯放在這裡而不是每個工具的字典裡（見 tools/base.py 的 IMPLICIT_*）。 */
const IMPLICIT_PORTS: Partial<Record<Language, Record<string, string>>> = {
  'zh-Hant': { _image: '影像（直通）', _overlays: '標記', _flow: '流程控制' },
  'zh-Hans': { _image: '图像（直通）', _overlays: '标记', _flow: '流程控制' },
}

export function localiseCatalogue(catalogue: ToolCatalogue, language: Language): ToolCatalogue {
  const dict = DICTS[language]
  if (!dict) return catalogue
  const categories = CATEGORIES[language] ?? {}
  const implicit = IMPLICIT_PORTS[language] ?? {}
  /** 埠：先看該工具的字典，再看共用的隱含埠（外掛沒有字典也拿得到隱含埠的翻譯）。 */
  const portLabel = (key: string, fallback: string, ports?: Record<string, string>) => ports?.[key] ?? implicit[key] ?? fallback
  return {
    ...catalogue,
    categories: (catalogue.categories ?? []).map((c) => ({ ...c, label: categories[c.key] ?? c.label })),
    items: (catalogue.items ?? []).map((def) => {
      const text = dict[def.key]
      // 分類名稱與隱含埠每個工具都有，沒有字典的工具（外掛）也要翻到
      const base = {
        ...def,
        category_label: categories[def.category] ?? def.category_label,
        inputs: (def.inputs ?? []).map((port) => ({ ...port, label: portLabel(port.key, port.label, text?.ports) })),
        outputs: (def.outputs ?? []).map((port) => ({ ...port, label: portLabel(port.key, port.label, text?.ports) })),
      }
      if (!text) return base
      return {
        ...base,
        label: text.label ?? def.label,
        description: text.description ?? def.description,
        params: (def.params ?? []).map((param) => {
          const p = text.params?.[param.key]
          if (!p) return param
          return {
            ...param,
            label: p.label ?? param.label,
            help_text: p.help ?? param.help_text,
            group: p.group ?? param.group,
            options: (param.options ?? []).map((o) => ({ ...o, label: p.options?.[String(o.value)] ?? o.label })),
          }
        }),
      }
    }),
  }
}
