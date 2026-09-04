/**
 * 整合方式的清單：路由、圖示、i18n key 與追蹤頻道。
 * 側欄的樹狀選單（AppShell）與整合頁的版面都讀這一份，加一種整合方式只要改這裡與路由。
 */
import { Cable, FileJson, Lock, Monitor, Plug, Radio, Send, Terminal } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

export interface IntegrationSection {
  /** 路由片段：/integration/<id> */
  id: string
  icon: LucideIcon
  /** i18n：integration.tabs.<id> */
  key: string
  /** 對應的整合追蹤頻道（沒有就不顯示命令與結果） */
  channel?: string
}

export const SECTIONS: IntegrationSection[] = [
  { id: 'http', icon: Send, key: 'http', channel: 'http' },
  { id: 'tcp', icon: Terminal, key: 'tcp', channel: 'tcp' },
  { id: 'events', icon: Radio, key: 'events' },
  { id: 'modbus', icon: Cable, key: 'modbus', channel: 'modbus' },
  { id: 'connections', icon: Plug, key: 'connections', channel: 'modbus' },
  { id: 'capture', icon: Monitor, key: 'capture', channel: 'capture' },
  { id: 'lock', icon: Lock, key: 'lock' },
  { id: 'format', icon: FileJson, key: 'format' },
]

export const SECTION_IDS = SECTIONS.map((s) => s.id)
export const DEFAULT_SECTION = 'http'

export function sectionOf(pathname: string): string {
  const match = /\/integration\/([a-z-]+)/.exec(pathname)
  return match && SECTION_IDS.includes(match[1]) ? match[1] : DEFAULT_SECTION
}
