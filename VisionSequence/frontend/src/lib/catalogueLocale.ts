/**
 * 後端目錄的翻譯（影像來源種類、連線種類、深度學習訓練方式、內建範本）。
 *
 * 與工具目錄（`toolLocale.ts`）同一套做法：**後端英文是唯一事實來源**，中文介面在這裡疊一層
 * 字典。翻譯只動顯示的文字，`kind`／`key` 這些**存進資料庫的值一律保持英文**，所以同一筆資料
 * 換語言看還是同一筆。沒有對照的項目（外掛）維持後端給的英文。
 *
 * 新增內建來源／連線／訓練方式／範本時，記得在兩份 `catalogue.zh-*.ts` 補一筆。
 */
import zhHans from '@/i18n/locales/catalogue.zh-Hans'
import zhHant from '@/i18n/locales/catalogue.zh-Hant'
import type { Language } from '@/i18n'
import type { DlTrainerDef, InspectKind, ToolParam } from '@/lib/types'

interface Entry {
  label?: string
  name?: string
  description?: string
}

/** 訓練方式的超參數：與工具參數同一種字典形狀（label／help／options）。 */
interface ParamText {
  label?: string
  help?: string
  options?: Record<string, string>
}

interface TrainerEntry extends Entry {
  params?: Record<string, ParamText>
}

interface CatalogueDict {
  inspectKinds?: Record<string, { label?: string; help?: string; fields?: Record<string, ParamText> }>
  sourceKinds?: Record<string, Entry>
  connectionKinds?: Record<string, Entry>
  trainers?: Record<string, TrainerEntry>
  /** 四種神經網路訓練方式共用的超參數（trainer 自己的 params 優先）。 */
  sharedParams?: Record<string, ParamText>
  /** Param.group 的名稱（Advanced／Augment），所有訓練方式共用。 */
  paramGroups?: Record<string, string>
  templates?: Record<string, Entry>
  /** seed_demo 建的示範資料（來源、流程、資產）的名稱：資料本身是英文，中文介面只換顯示。 */
  dataNames?: Record<string, string>
}

/** 示範資料的名稱翻譯（只在下拉與清單顯示用；使用者自己命名的資料原樣顯示）。 */
export function localiseDataName(name: string, language: Language): string {
  return DICTS[language]?.dataNames?.[name] ?? name
}

export function localiseInspectKinds(items: InspectKind[], language: Language): InspectKind[] {
  return items.map((item) => {
    const text = DICTS[language]?.inspectKinds?.[item.kind]
    if (!text) return item
    return { ...item, label: text.label ?? item.label, help_text: text.help ?? item.help_text,
      fields: item.fields.map((field) => {
        const words = text.fields?.[field.key]
        return { ...field, label: words?.label ?? field.label, help_text: words?.help ?? field.help_text,
          options: field.options.map((option) => ({ ...option, label: words?.options?.[option.value] ?? option.label })) }
      }),
    }
  })
}

const DICTS: Partial<Record<Language, CatalogueDict>> = {
  'zh-Hant': zhHant as CatalogueDict,
  'zh-Hans': zhHans as CatalogueDict,
}

type Section = 'sourceKinds' | 'connectionKinds' | 'trainers' | 'templates'

/** 一筆目錄項目：翻譯 label／name／description，其餘欄位（尤其是 key）原樣保留。 */
export function localiseEntry<T extends { label?: string; name?: string; description?: string }>(
  section: Section,
  key: string,
  item: T,
  language: Language,
): T {
  const text = DICTS[language]?.[section]?.[key]
  if (!text) return item
  return {
    ...item,
    ...(text.label && item.label !== undefined ? { label: text.label } : {}),
    ...(text.name && item.name !== undefined ? { name: text.name } : {}),
    ...(text.description ? { description: text.description } : {}),
  }
}

/** 一整份目錄；`keyOf` 說明哪個欄位是識別碼（來源與連線是 kind、範本是 key）。 */
export function localiseList<T extends { label?: string; name?: string; description?: string }>(
  section: Section,
  items: T[],
  keyOf: (item: T) => string,
  language: Language,
): T[] {
  if (!DICTS[language]) return items
  return items.map((item) => localiseEntry(section, keyOf(item), item, language))
}

function localiseParam(param: ToolParam, text: ParamText | undefined, groups: Record<string, string>): ToolParam {
  const group = param.group ? groups[param.group] ?? param.group : param.group
  if (!text) return group === param.group ? param : { ...param, group }
  return {
    ...param,
    group,
    label: text.label ?? param.label,
    help_text: text.help ?? param.help_text,
    options: (param.options ?? []).map((o) => ({ ...o, label: text.options?.[String(o.value)] ?? o.label })),
  }
}

/** 訓練方式：名稱、說明，加上超參數的名稱／說明／選項與分組名稱。神經網路四種共用一份參數字典。 */
export function localiseTrainers(items: DlTrainerDef[], language: Language): DlTrainerDef[] {
  const dict = DICTS[language]
  if (!dict) return items
  const groups = dict.paramGroups ?? {}
  return items.map((trainer) => {
    const text = dict.trainers?.[trainer.kind]
    const shared = trainer.kind.startsWith('ai_') ? dict.sharedParams ?? {} : {}
    return {
      ...trainer,
      label: text?.label ?? trainer.label,
      description: text?.description ?? trainer.description,
      params: (trainer.params ?? []).map((p) => localiseParam(p, text?.params?.[p.key] ?? shared[p.key], groups)),
    }
  })
}
