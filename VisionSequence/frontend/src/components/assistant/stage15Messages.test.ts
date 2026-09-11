/** 階段 15 對話驗收：後端英文訊息要換成介面語言、恢復卡不顯示原始 JSON。 */
import { afterEach, describe, expect, it } from 'vitest'
import i18n from '@/i18n'
import { tasklistMessage } from './TaskListCard'
import { resumeValue } from './ResumeCard'

afterEach(async () => { await i18n.changeLanguage('en') })

describe('stage 15 assistant messages', () => {
  it('translates known task list messages and keeps unknown text', async () => {
    await i18n.changeLanguage('zh-Hant')
    const t = i18n.t.bind(i18n)
    expect(tasklistMessage(t, 'Confirm required fields: template_images')).toBe('請先確認必填欄位：template_images。')
    expect(tasklistMessage(t, 'Choose the locate task to use.')).toBe('請選擇這些任務要跟隨的定位任務。')
    expect(tasklistMessage(t, 'Several tasks match. Say which item to change, for example "item 2".')).toContain('第 2 項')
    expect(tasklistMessage(t, "The assistant could not be reached (the provider's request limit was reached). The offline parser was used instead; review every value.")).toContain('請求上限')
    expect(tasklistMessage(t, 'Something new')).toBe('Something new')
  })

  it('formats resume values without raw JSON', () => {
    expect(resumeValue(638.5751593868889)).toBe('638.575')
    expect(resumeValue({ shape: 'annulus', cx: 1 })).toBe('annulus')
    expect(resumeValue(null)).toBe('-')
    expect(resumeValue([1, 2])).toBe('2')
    expect(resumeValue('ok')).toBe('ok')
  })
})
