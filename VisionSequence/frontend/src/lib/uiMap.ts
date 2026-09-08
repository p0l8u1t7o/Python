/**
 * 介面地圖：每個頁面的路由、側欄名稱、需要的功能鍵、分頁與主要動作（都以 i18n key 指到實際顯示的文字）。
 * `scripts/ui_map.mjs` 用三種語系解析後寫成 apps/vision/agent/ui_map.json，讓 AI 助手用使用者看到的字告訴他「到哪裡、按什麼」；
 * `uiMap.test.ts` 確保 App.tsx 的每條路由都在這裡、每個 key 三語系都解得到、JSON 沒有過期。
 */
import type { Feature } from '@/lib/types'

export interface UiPage {
  /** 路由樣板（與 App.tsx 一致） */
  route: string
  /** 穩定鍵（後端 sources[].page） */
  id: string
  /** 側欄項目的 i18n key（nav.<key>） */
  nav?: string
  /** 沒有側欄項目時的標題 i18n key */
  title?: string
  /** 進得去要有的功能鍵（管理員永遠可以） */
  feature?: Feature
  admin?: boolean
  /** help.content.pages 的路由欄（頁面用途的說明從那張表來） */
  help: string
  /** 分頁（SectionTabs／Tabs 的 key 與 label i18n key） */
  tabs?: { key: string; label: string }[]
  /** 主要動作的 i18n key（按鈕文字） */
  actions?: string[]
}

const TRACE = { key: 'trace', label: 'integration.trace.title' }

export const UI_PAGES: UiPage[] = [
  { route: '/', id: 'dashboard', nav: 'nav.dashboard', help: '/', actions: ['dashboard.runOnce'] },
  { route: '/flows', id: 'flows', nav: 'nav.flows', help: '/flows', actions: ['flows.create', 'flows.export'] },
  { route: '/flows/:flowId', id: 'flow_editor', title: 'breadcrumb.editor', feature: 'flows.edit', help: '/flows/:id', actions: ['editor.save', 'editor.preview', 'editor.export'] },
  { route: '/flows/:flowId/tools/:nodeId', id: 'tool', title: 'breadcrumb.tools', feature: 'flows.edit', help: '/flows/:id/tools/:nodeId' },
  { route: '/flows/:flowId/stats', id: 'stats', title: 'breadcrumb.stats', help: '/flows/:id/stats' },
  { route: '/flows/:flowId/teach', id: 'teach', title: 'breadcrumb.teach', feature: 'flows.teach', help: '/flows/:id/teach', actions: ['teach.saveGraph', 'teach.saveRecipe'] },
  { route: '/flows/:flowId/golden', id: 'golden', title: 'breadcrumb.golden', feature: 'golden', help: '/flows/:id/golden', actions: ['golden.upload', 'golden.regress'] },
  { route: '/batch', id: 'batch', nav: 'nav.batch', feature: 'batch', help: '/batch',
    tabs: [{ key: 'result', label: 'batchPage.tabs.result' }, { key: 'images', label: 'batchPage.tabs.images' }, { key: 'insights', label: 'batchPage.tabs.insights' }, { key: 'compare', label: 'batchPage.tabs.compare' }, { key: 'tune', label: 'batchPage.tabs.tune' }],
    actions: ['batchPage.newSet', 'batchPage.run', 'batchPage.toGolden'] },
  { route: '/dl', id: 'dl', nav: 'nav.dl', feature: 'dl', help: '/dl', actions: ['dl.newProject', 'dl.upload', 'dl.train', 'dl.createFlow'] },
  { route: '/agent', id: 'agent', nav: 'nav.agent', feature: 'agent', help: '/agent', actions: ['agent.upload', 'agent.addRoi'] },
  { route: '/integration', id: 'integration', nav: 'nav.integration', feature: 'integration', help: '/integration' },
  { route: '/integration/http', id: 'integration_http', title: 'integration.tabs.http', feature: 'integration', help: '/integration',
    tabs: [{ key: 'try', label: 'integration.sections.try' }, { key: 'format', label: 'integration.sections.format' }, TRACE] },
  { route: '/integration/tcp', id: 'integration_tcp', title: 'integration.tabs.tcp', feature: 'integration', help: '/integration',
    tabs: [{ key: 'try', label: 'integration.sections.try' }, { key: 'rules', label: 'integration.sections.rules' }, { key: 'codes', label: 'integration.sections.codes' }, { key: 'connections', label: 'integration.sections.connections' }, TRACE], actions: ['connections.create'] },
  { route: '/integration/events', id: 'integration_events', title: 'integration.tabs.events', feature: 'integration', help: '/integration' },
  { route: '/integration/modbus-server', id: 'integration_modbus_server', title: 'integration.tabs.modbusServer', feature: 'integration', help: '/integration',
    tabs: [{ key: 'connections', label: 'integration.sections.connections' }, { key: 'guide', label: 'integration.sections.guide' }, TRACE], actions: ['connections.create'] },
  { route: '/integration/modbus-client', id: 'integration_modbus_client', title: 'integration.tabs.modbusClient', feature: 'integration', help: '/integration',
    tabs: [{ key: 'connections', label: 'integration.sections.connections' }, { key: 'guide', label: 'integration.sections.guide' }, TRACE], actions: ['connections.create'] },
  { route: '/integration/capture', id: 'integration_capture', title: 'integration.tabs.capture', feature: 'integration', help: '/integration',
    tabs: [{ key: 'clients', label: 'integration.sections.clients' }, TRACE] },
  { route: '/integration/plugins', id: 'integration_plugins', title: 'integration.tabs.plugins', feature: 'integration', help: '/integration',
    tabs: [{ key: 'inventory', label: 'integration.sections.inventory' }, { key: 'connections', label: 'integration.sections.connections' }], actions: ['integration.plugins.rescan', 'connections.create'] },
  { route: '/help', id: 'help', nav: 'nav.help', help: '/help',
    tabs: [{ key: 'quickstart', label: 'help.tabs.quickstart' }, { key: 'glossary', label: 'help.tabs.glossary' }, { key: 'ports', label: 'help.tabs.ports' }, { key: 'tools', label: 'help.tabs.tools' }, { key: 'shortcuts', label: 'help.tabs.shortcuts' }, { key: 'automation', label: 'help.tabs.automation' }, { key: 'accounts', label: 'help.tabs.accounts' }] },
  { route: '/sources', id: 'sources', nav: 'nav.sources', feature: 'sources', help: '/sources', actions: ['sources.create', 'sources.test'] },
  { route: '/assets', id: 'assets', nav: 'nav.assets', feature: 'assets', help: '/assets', actions: ['assets.upload'] },
  { route: '/calibration', id: 'calibration', nav: 'nav.calibration', feature: 'assets', help: '/calibration', actions: ['calibration.capture', 'calibration.calculate', 'calibration.save'] },
  { route: '/users', id: 'users', nav: 'nav.users', admin: true, help: '/users', actions: ['users.create', 'permissions.title'] },
  { route: '/audit', id: 'audit', nav: 'nav.audit', feature: 'audit', help: '/audit', actions: ['audit.export'] },
  { route: '/settings', id: 'settings', nav: 'nav.settings', help: '/settings', actions: ['auth.changePassword'] },
  { route: '/login', id: 'login', title: 'auth.loginTitle', help: '/login' },
  { route: '/board/:flowId', id: 'board', title: 'board.settings.title', help: '/board/:flowId' },
]

/** 不進地圖的路由：純轉址。 */
export const REDIRECT_ROUTES = ['/connections', '/integration/modbus', '/integration/*']

export interface UiMapJson {
  generated_from: string
  languages: string[]
  pages: {
    route: string
    id: string
    names: Record<string, string>
    summary: Record<string, string>
    feature?: string
    admin?: boolean
    tabs?: { key: string; names: Record<string, string> }[]
    actions?: Record<string, string>[]
  }[]
}

type Translate = (lang: string, key: string) => string
type HelpPages = (lang: string) => [string, string, string, string][]

/** 用三種語系把地圖解析成後端要的 JSON（產生器與測試共用；找不到的 key 直接拋錯，避免地圖與字典脫節）。 */
export function buildUiMap(languages: string[], t: Translate, helpPages: HelpPages): UiMapJson {
  const summaries = new Map<string, Record<string, string>>()
  for (const lang of languages) {
    for (const row of helpPages(lang)) {
      const bucket = summaries.get(row[1]) ?? {}
      bucket[lang] = row[3]
      summaries.set(row[1], bucket)
    }
  }
  const names = (key: string) => Object.fromEntries(languages.map((lang) => [lang, t(lang, key)]))
  return {
    generated_from: 'frontend/src/lib/uiMap.ts',
    languages,
    pages: UI_PAGES.map((p) => {
      const summary = summaries.get(p.help)
      if (!summary) throw new Error(`help.content.pages has no row for ${p.help} (${p.id})`)
      return {
        route: p.route,
        id: p.id,
        names: names(p.nav ?? p.title ?? ''),
        summary,
        ...(p.feature ? { feature: p.feature } : {}),
        ...(p.admin ? { admin: true } : {}),
        ...(p.tabs ? { tabs: p.tabs.map((tab) => ({ key: tab.key, names: names(tab.label) })) } : {}),
        ...(p.actions ? { actions: p.actions.map((a) => names(a)) } : {}),
      }
    }),
  }
}
