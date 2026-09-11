/**
 * 工具與引擎的執行訊息：後端給英文句子＋代碼與參數（apps/vision/tools/messages.py 的 Msg），
 * 這裡依介面語言套中文樣板；沒有代碼、英文介面或字典沒有這一條，就顯示後端的英文。
 */
import toolMessagesZhHans from '@/i18n/locales/toolMessages.zh-Hans'
import toolMessagesZhHant from '@/i18n/locales/toolMessages.zh-Hant'

const DICTS: Record<string, Record<string, string>> = { 'zh-Hant': toolMessagesZhHant, 'zh-Hans': toolMessagesZhHans }

export function localiseMessage(text: string, code: string | null | undefined, args: Record<string, string> | null | undefined, language: string): string {
  if (!code) return text
  const template = DICTS[language]?.[code]
  if (!template) return text
  const sentence = template.replace(/\{(\w+)\}/g, (whole, key: string) => (args && key in args ? String(args[key]) : whole))
  // 比較工具判 NG 時使用者填的標籤（base.apply_reject）：英文是「句子 (標籤)」，中文同樣接在後面
  const label = args?.ng_label
  return label && !template.includes('{ng_label}') ? `${sentence} (${label})` : sentence
}

export function nodeMessage(report: { message?: string; message_code?: string; message_args?: Record<string, string> } | null | undefined, language: string): string {
  return report?.message ? localiseMessage(report.message, report.message_code, report.message_args, language) : ''
}
