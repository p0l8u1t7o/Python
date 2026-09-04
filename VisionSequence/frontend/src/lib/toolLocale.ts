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

export function localiseCatalogue(catalogue: ToolCatalogue, language: Language): ToolCatalogue {
  const dict = DICTS[language]
  if (!dict) return catalogue
  const categories = CATEGORIES[language] ?? {}
  return {
    ...catalogue,
    categories: (catalogue.categories ?? []).map((c) => ({ ...c, label: categories[c.key] ?? c.label })),
    items: (catalogue.items ?? []).map((def) => {
      const text = dict[def.key]
      if (!text) return def
      return {
        ...def,
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
        inputs: (def.inputs ?? []).map((port) => ({ ...port, label: text.ports?.[port.key] ?? port.label })),
        outputs: (def.outputs ?? []).map((port) => ({ ...port, label: text.ports?.[port.key] ?? port.label })),
      }
    }),
  }
}
