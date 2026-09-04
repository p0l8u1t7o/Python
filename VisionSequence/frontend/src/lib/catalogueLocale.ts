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

interface Entry {
  label?: string
  name?: string
  description?: string
}

interface CatalogueDict {
  sourceKinds?: Record<string, Entry>
  connectionKinds?: Record<string, Entry>
  trainers?: Record<string, Entry>
  templates?: Record<string, Entry>
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

/** 一整份目錄；`keyOf` 說明哪個欄位是識別碼（來源與連線是 kind、訓練方式是 kind、範本是 key）。 */
export function localiseList<T extends { label?: string; name?: string; description?: string }>(
  section: Section,
  items: T[],
  keyOf: (item: T) => string,
  language: Language,
): T[] {
  if (!DICTS[language]) return items
  return items.map((item) => localiseEntry(section, keyOf(item), item, language))
}
