/**
 * 說明頁（HelpPage）`/help`：快速上手、名詞定義（docs/glossary.html 的表）、埠型別與顏色圖例、
 * 工具目錄（從 /tool-types 動態列出）、快捷鍵、自動化接口摘要、帳號與鎖定。
 * 名詞表是文件內容，直接以繁中呈現（程式名保持原文）；分頁標題與欄位名走 i18n。
 */
import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router-dom'
import { Plug } from 'lucide-react'

import { iconFor } from '@/components/editor/ToolNode'
import { Page } from '@/components/layout/AppShell'
import { Button, Card, CardBody, CardHeader, LoadingState, PageHeader, Tabs } from '@/components/ui'
import { PORT_HEX } from '@/lib/ports'
import { useToolTypes } from '@/lib/queries'
import type { PortType } from '@/lib/types'

type HelpTab = 'quickstart' | 'glossary' | 'ports' | 'tools' | 'shortcuts' | 'automation' | 'accounts'
const TABS: HelpTab[] = ['quickstart', 'glossary', 'ports', 'tools', 'shortcuts', 'automation', 'accounts']

const QUICKSTART: { title: string; body: string }[] = [
  { title: '建流程', body: '到「流程」頁按「新增流程」，或複製示範流程。每位使用者各自擁有流程；共用流程只有管理員能改。' },
  { title: '取像', body: '從工具箱插入「影像來源」步驟：選影像來源庫裡的相機／資料夾／合成來源，或用頂列「上傳暫存影像」只為試跑放一張圖（不進來源庫）。' },
  { title: '加工具', body: '把工具箱的工具拖到畫布（或點一下插到最右邊），把上一步的輸出埠拉線接到下一步的輸入埠；同色的埠才能相接。' },
  { title: 'ROI', body: '有「區域」參數的工具：在工具頁或側欄按「在影像上編輯」，直接在影像視窗拖曳畫出矩形／圓／多邊形等；座標是該步驟輸入影像的像素座標。' },
  { title: '試跑', body: '頂列「試跑」用目前畫布（未存檔）的圖執行一次，保留所有中間影像；「用上次影像重跑」可固定同一張影像調參。點步驟名稱旁的圖示開「工具頁」，改參數會自動重跑到該步驟並顯示前／後影像與直方圖。' },
  { title: '判定', body: '用「判定」工具給出 OK／NG；用「具名輸出」把要回傳給自動化系統的值命名。' },
  { title: '儲存', body: 'Ctrl+S 或頂列「儲存」。「執行一次」與「連續執行」用的是已儲存的版本。' },
  { title: '自動化觸發', body: '外部系統用 HTTP POST /api/vision/flows/{id}/run（可附影像）或 TCP 指令觸發；結果經 SSE 或回應取得。細節見「自動化接口」分頁。' },
]

const GLOSSARY_PAGES: [string, string, string, string][] = [
  ['總覽', '/', 'DashboardPage', '所有流程的即時狀態卡片'],
  ['流程', '/flows', 'FlowsPage', '流程清單'],
  ['流程編輯器', '/flows/:id', 'FlowEditorPage', '畫布＋影像視窗＋側欄'],
  ['工具頁', '/flows/:id/tools/:nodeId', 'ToolPage', '單一步驟的專屬調參頁'],
  ['影像來源庫', '/sources', 'SourcesPage', '相機／資料夾／合成來源的清單'],
  ['資產庫', '/assets', 'AssetsPage', '範本影像、模型檔'],
  ['使用者', '/users', 'UsersPage', '帳號管理（管理員）'],
  ['設定', '/settings', 'SettingsPage', '金鑰、主題、語言、引擎鎖定、密碼'],
  ['說明', '/help', 'HelpPage', '名詞定義與操作說明'],
  ['整合頁', '/integration', 'IntegrationPage', 'HTTP／TCP 測試工具、事件監看、鎖定、回傳格式'],
  ['統計', '/flows/:id/stats', 'StatsPage', '執行歷史、良率趨勢、每小時 OK／NG'],
  ['參數卡', '/flows/:id/teach', 'TeachPage', '全流程教導參數依步驟分組、即時試跑；配方下拉；標記為已教導'],
  ['Golden Set', '/flows/:id/golden', 'GoldenPage', '有期望值的影像案例與回歸測試（退步清單置頂）'],
  ['連線', '/connections', 'ConnectionsPage', 'Modbus TCP／上位機的主動輸出連線：測試、手動寫入、狀態'],
  ['登入', '/login', 'LoginPage', '登入／建立第一個管理員'],
]

const GLOSSARY_EDITOR: [string, string, string][] = [
  ['頂列', 'EditorToolbar', '兩列：流程名稱、儲存、範本、配方、綁定；試跑、用上次影像、上傳暫存影像、連續執行、重置、說明'],
  ['工具箱', 'ToolPalette', '左欄上半：可插入的工具（依類別分組、可搜尋；拖到畫布新增）'],
  ['步驟清單', 'NodeList', '左欄下半：本流程所有步驟；點一下畫布聚焦到該步驟'],
  ['影像視窗', 'ImageViewer', '中欄上方：顯示影像、標記、ROI 編輯'],
  ['畫布', 'FlowCanvas', '中欄下方：React Flow 畫布'],
  ['側欄', 'Inspector', '右欄：流程共用設定／選取步驟的基本設定與「開啟工具頁」'],
  ['結果分頁', 'ResultsPanel', '側欄的「結果」分頁：最近執行、輸出值、錯誤、警告'],
  ['配方管理', 'RecipeManager', '參數卡頁的「管理配方」Modal：新增／改名／設預設／刪除、覆寫表'],
  ['鎖定橫幅', 'LockBanner', '引擎鎖定時的黃色橫幅'],
]

const GLOSSARY_CORE: [string, string, string][] = [
  ['流程', 'Flow', '一張檢測圖（步驟＋連線）；每位使用者各自擁有'],
  ['教導參數 / 參數卡', 'Teach param / Teach page', '工具以 teach=True 標記的現場調機參數；參數卡頁只列這些'],
  ['已教導', 'Commissioned', '參數卡頁「標記為已教導」；未教導的流程執行會帶警告但不阻擋'],
  ['配方', 'Recipe (FlowRecipe)', '同一流程的一組參數覆寫，多料號換線用；執行／試跑／TCP recipe= 可指定，未指定用預設配方'],
  ['Golden Set / 案例', 'Golden case', '有期望值（OK／NG／不限）的影像；來自上傳或批次測試結果'],
  ['回歸 / 基準', 'Regression / Baseline', '跑全部案例與期望值和基準比對；退步 = 基準符合、這次不符'],
  ['站台', 'Station (station_id)', '每筆 run 帶的站台代號（VISION_STATION_ID）'],
  ['連線', 'Connection', '主動輸出到 Modbus TCP／上位機的連線（modbus_tcp／tcp_client／dio_sim／plugin）；write_modbus 以名稱引用'],
  ['匯出 / 匯入', 'Export / Import (.flow.json)', '穩定序列化的流程檔；匯入依名稱 upsert，{SOURCE} 佔位以選的來源取代'],
  ['步驟', 'Node', '畫布上的一個方塊；一個步驟就是一個工具的實例'],
  ['工具', 'Tool（ToolTypeDef）', '工具箱裡的種類（灰階、Blob…）；key 是唯一識別字'],
  ['連線', 'Edge', '步驟之間的線：來源輸出埠 → 目標輸入埠'],
  ['埠', 'Port', '步驟左側為輸入埠、右側為輸出埠；有型別'],
  ['分支把手', 'Flow handle', '型別為 flow 的輸出埠（true／false 等），只能接到步驟的「控制輸入」（菱形）'],
  ['參數', 'Param', '步驟的設定值；種類是封閉集合（number、select、roi…）'],
  ['區域 / ROI', 'Region', '在影像上畫的檢測範圍（矩形、旋轉矩形、圓、環、多邊形、線）'],
  ['標記', 'Overlay', '工具畫在影像上的結果圖形（框、圓、點、文字…）'],
  ['執行', 'Run', '一次完整（或到某步驟為止）的流程執行；結果為 OK／NG／失敗'],
  ['試跑', 'Preview', '用未儲存的圖執行、保留所有中間影像；不寫入歷史'],
  ['執行一次', 'Run once', '用已儲存的圖執行一次；寫入歷史與統計'],
  ['連續執行', 'Continuous', '依間隔不停執行'],
  ['暫存影像', 'Scratch image', '只為試跑上傳的影像，不進影像來源庫'],
  ['影像來源', 'Image source', '相機／資料夾／合成／API 送圖的定義'],
  ['資產', 'Asset', '範本影像、ONNX 模型等檔案'],
  ['判定', 'Judge', 'OK／NG 的結論（judge 工具）'],
  ['具名輸出', 'Output', '回傳給自動化系統的鍵值（output 工具）'],
  ['引擎鎖定', 'Engine lock', '整合方鎖住硬體：其他人只能編輯不能執行'],
  ['整合方', 'Integrator', '以 API 金鑰呼叫的自動化系統'],
  ['重置', 'Reset', '清除該流程在記憶體內的執行紀錄與統計'],
  ['範本庫', 'Template library', '流程範本（內建／自訂）；從範本建立流程或載入到畫布、把畫布存為範本'],
  ['批次測試', 'Batch test', '多張影像用目前的圖跑一輪，看良率與每張判定'],
  ['收藏', 'Favorites', '工具箱裡加星號的工具（存在瀏覽器）'],
]

const GLOSSARY_STATUS: [string, string, string][] = [
  ['OK', '綠', '判定合格'],
  ['NG', '紅', '判定不良'],
  ['失敗', '深紅框', '工具錯誤／逾時／沒有影像；畫布上該步驟顯示錯誤訊息'],
  ['略過', '灰淡', '分支未選中或上游失敗'],
  ['執行中', '脈動邊框', '正在跑'],
]

const PORT_ROWS: [PortType, string, string][] = [
  ['image', '藍', '影像'],
  ['region', '紫', 'ROI'],
  ['number', '綠', '數值'],
  ['bool', '橘', '布林'],
  ['string', '黃', '字串'],
  ['points', '青', '點集合'],
  ['contours', '靛', '輪廓'],
  ['matches', '粉', '比對／偵測結果'],
  ['list', '藍綠', '一般清單（含標記）'],
  ['any', '灰白', '任意'],
  ['flow', '灰（菱形）', '分支'],
]

const SHORTCUTS: [string, string][] = [
  ['Ctrl+S', '儲存流程'],
  ['右鍵點步驟', '步驟選單：開啟工具頁、複製、停用、刪除、複製／貼上參數'],
  ['Ctrl+Z', '復原'],
  ['Ctrl+C / Ctrl+V', '複製／貼上選取的步驟（含內部連線）'],
  ['Delete / Backspace', '刪除選取的步驟或連線'],
  ['Esc', '取消選取／結束 ROI 編輯'],
  ['左鍵拖曳（選取模式）', '框選多個步驟；中鍵／右鍵拖曳平移畫布'],
  ['Shift+拖曳（平移模式）', '框選'],
  ['滾輪', '影像視窗與畫布縮放'],
  ['F / 1 / + / −（影像視窗）', '符合視窗／1:1／放大／縮小'],
  ['雙擊影像', '符合視窗'],
]

const AUTOMATION = [
  { title: 'HTTP 觸發', code: 'POST /api/vision/flows/{id}/run?wait=1\nHeaders: X-API-Key: <金鑰>（或 Authorization: Bearer <token>）\nmultipart: image=<檔案>  或  JSON: {"context": {...}}\n→ 200 RunReport（wait=1）／202 {"queued": true}（wait=0）' },
  { title: '試跑（工具頁同款）', code: 'POST /api/vision/flows/{id}/preview\n{"graph": {...}, "reuse_image_ref": "...", "until_node": "blob", "analysis": true}' },
  { title: '暫存影像 / 重置', code: 'POST /api/vision/flows/{id}/scratch-image（multipart image）→ {ref,width,height,name}\nDELETE /api/vision/flows/{id}/recent → 清除記憶體內執行紀錄與統計（SSE 收到 cleared）' },
  { title: '事件串流（SSE）', code: 'GET /api/vision/flows/{id}/stream?since=<seq>\n事件：run_started / run_finished（帶 run）/ stats / continuous / lock / cleared / ping（15 秒心跳）' },
  { title: 'TCP', code: '一行一個指令（\\n 結尾，大小寫不拘），一行 JSON 回應：\nRUN <flow_id 或 名稱> [key=value ...] → {"ok": true, "status": "ok|ng|failed", "judge": "OK", "outputs": {...}, "duration_ms": 12.3, "run_id": "..."}\nTRIGGER <flow>   → 只觸發不等結果 {"ok": true, "queued": true}\nSTATUS [flow]    → 統計\nSTART <flow> / STOP <flow> → 連續執行\nLIST / PING\n影像由影像來源 kind=upload 以 POST /api/vision/sources/{id}/push 送入。' },
]

const ACCOUNTS = [
  '第一次使用時系統沒有任何使用者，登入頁會直接讓你建立第一個管理員。',
  '管理員：管理使用者、修改共用流程、鎖定／解鎖引擎。一般使用者：只能修改自己擁有的流程；共用流程請先「複製」。',
  '整合方（自動化系統）用 API 金鑰（X-API-Key）呼叫，永遠可執行流程。',
  '引擎鎖定：整合方或管理員在「設定」頁鎖定後，所有連續執行停止；其他人只能編輯、不能試跑或執行（頂列會顯示「引擎已鎖定」）；鎖可設定自動解鎖秒數。',
  '密碼在左下角使用者選單「修改密碼」；管理員可在「使用者」頁重設他人密碼、停用帳號。',
]

function Table({ head, rows }: { head: string[]; rows: (string | React.ReactNode)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr>{head.map((h) => <th key={h} className="table-header">{h}</th>)}</tr>
        </thead>
        <tbody className="divide-y divide-line">
          {rows.map((row, i) => (
            <tr key={i}>{row.map((cell, j) => <td key={j} className={`table-cell ${j === 1 ? 'font-mono text-xs' : ''}`}>{cell}</td>)}</tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function ToolsCatalogue() {
  const { t } = useTranslation()
  const catalogue = useToolTypes()
  const groups = useMemo(() => {
    const map = new Map<string, { label: string; items: NonNullable<typeof catalogue.data>['items'] }>()
    for (const def of catalogue.data?.items ?? []) {
      const g = map.get(def.category) ?? { label: def.category_label, items: [] }
      g.items.push(def)
      map.set(def.category, g)
    }
    return [...map.values()]
  }, [catalogue.data])
  if (catalogue.isPending) return <LoadingState compact />
  return (
    <div className="space-y-4" data-testid="help-tools">
      {groups.map((group) => (
        <Card key={group.label}>
          <CardHeader title={group.label} description={t('help.toolsCount', { count: group.items.length })} />
          <CardBody className="divide-y divide-line !p-0">
            {group.items.map((def) => {
              const Icon = iconFor(def.icon)
              return (
                <div key={def.key} className="px-4 py-3">
                  <p className="flex items-center gap-2 text-sm font-semibold">
                    <Icon size={15} className="text-brand" /> {def.label}
                    <span className="font-mono text-[11px] font-normal text-muted">{def.key}</span>
                    {def.heavy ? <span className="text-[11px] font-normal text-warning">{t('editor.heavy')}</span> : null}
                  </p>
                  {def.description ? <p className="mt-0.5 text-xs text-muted">{def.description}</p> : null}
                  <div className="mt-1.5 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-2">
                    <p>
                      <span className="font-medium text-muted">{t('editor.inputs')}：</span>
                      {def.inputs.length ? def.inputs.map((p, i) => (
                        <span key={`${p.key}-${i}`} className="mr-2 inline-flex items-center gap-1">
                          <span className="inline-block size-2 rounded-full" style={{ background: PORT_HEX[p.type] }} />{p.label}<span className="text-subtle">({p.type}{p.required ? '' : '?'})</span>
                        </span>
                      )) : '—'}
                    </p>
                    <p>
                      <span className="font-medium text-muted">{t('editor.outputs')}：</span>
                      {def.outputs.filter((p) => !p.implicit).map((p, i) => (
                        <span key={`${p.key}-${i}`} className="mr-2 inline-flex items-center gap-1">
                          <span className={`inline-block size-2 ${p.type === 'flow' ? 'rotate-45' : 'rounded-full'}`} style={{ background: PORT_HEX[p.type] }} />{p.label}<span className="text-subtle">({p.type})</span>
                        </span>
                      ))}
                    </p>
                  </div>
                  {def.params.length ? (
                    <p className="mt-1 text-xs">
                      <span className="font-medium text-muted">{t('editor.parameters')}：</span>
                      {def.params.map((p) => `${p.label}（${p.kind}${p.unit ? `, ${p.unit}` : ''}）`).join('、')}
                    </p>
                  ) : null}
                </div>
              )
            })}
          </CardBody>
        </Card>
      ))}
    </div>
  )
}

export function HelpPage() {
  const { t } = useTranslation()
  const [params, setParams] = useSearchParams()
  const initial = params.get('tab') as HelpTab | null
  const [tab, setTab] = useState<HelpTab>(initial && TABS.includes(initial) ? initial : 'quickstart')
  const change = (next: HelpTab) => {
    setTab(next)
    setParams({ tab: next }, { replace: true })
  }
  return (
    <Page>
      <PageHeader title={t('help.title')} description={t('help.subtitle')} />
      <Tabs value={tab} onChange={change} tabs={TABS.map((value) => ({ value, label: t(`help.tabs.${value}`) }))} className="mb-4 flex-wrap" />
      <div data-testid={`help-${tab}`}>
        {tab === 'quickstart' ? (
          <ol className="space-y-3">
            {QUICKSTART.map((step, i) => (
              <li key={step.title} className="card flex gap-3 p-4">
                <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-brand-soft text-sm font-bold text-brand">{i + 1}</span>
                <div>
                  <p className="text-sm font-semibold">{step.title}</p>
                  <p className="mt-0.5 text-sm leading-relaxed text-muted">{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        ) : null}
        {tab === 'glossary' ? (
          <div className="space-y-4">
            <Card><CardHeader title={t('help.glossary.pages')} /><CardBody className="!p-0"><Table head={[t('help.cols.zh'), t('help.cols.route'), t('help.cols.code'), t('help.cols.desc')]} rows={GLOSSARY_PAGES} /></CardBody></Card>
            <Card><CardHeader title={t('help.glossary.editor')} /><CardBody className="!p-0"><Table head={[t('help.cols.zh'), t('help.cols.code'), t('help.cols.desc')]} rows={GLOSSARY_EDITOR} /></CardBody></Card>
            <Card><CardHeader title={t('help.glossary.core')} /><CardBody className="!p-0"><Table head={[t('help.cols.zh'), t('help.cols.en'), t('help.cols.def')]} rows={GLOSSARY_CORE} /></CardBody></Card>
            <Card><CardHeader title={t('help.glossary.status')} /><CardBody className="!p-0"><Table head={[t('help.cols.status'), t('help.cols.color'), t('help.cols.desc')]} rows={GLOSSARY_STATUS} /></CardBody></Card>
          </div>
        ) : null}
        {tab === 'ports' ? (
          <Card>
            <CardHeader title={t('help.tabs.ports')} description={t('help.portsHint')} />
            <CardBody className="!p-0">
              <Table
                head={[t('help.cols.type'), t('help.cols.color'), t('help.cols.usage')]}
                rows={PORT_ROWS.map(([type, color, usage]) => [
                  <span key="t" className="inline-flex items-center gap-2 font-mono text-xs">
                    <span className={`inline-block size-3 border-2 border-surface ${type === 'flow' ? 'rotate-45' : 'rounded-full'}`} style={{ background: PORT_HEX[type] }} />
                    {type}
                  </span>,
                  `${color} ${PORT_HEX[type]}`,
                  usage,
                ])}
              />
            </CardBody>
          </Card>
        ) : null}
        {tab === 'tools' ? <ToolsCatalogue /> : null}
        {tab === 'shortcuts' ? (
          <Card><CardBody className="!p-0"><Table head={[t('help.cols.key'), t('help.cols.action')]} rows={SHORTCUTS.map(([k, v]) => [<kbd key="k" className="rounded border border-line bg-surface-muted px-1.5 py-0.5 font-mono text-xs">{k}</kbd>, v])} /></CardBody></Card>
        ) : null}
        {tab === 'automation' ? (
          <div className="space-y-3">
            <Card>
              <CardBody className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-sm text-muted">{t('integration.subtitle')}</p>
                <Link to="/integration"><Button variant="primary" icon={<Plug size={14} />} data-testid="help-goto-integration">{t('integration.title')}</Button></Link>
              </CardBody>
            </Card>
            {AUTOMATION.map((item) => (
              <Card key={item.title}>
                <CardHeader title={item.title} />
                <CardBody><pre className="overflow-x-auto whitespace-pre-wrap rounded-lg bg-surface-muted p-3 font-mono text-xs leading-relaxed">{item.code}</pre></CardBody>
              </Card>
            ))}
          </div>
        ) : null}
        {tab === 'accounts' ? (
          <Card>
            <CardHeader title={t('help.tabs.accounts')} />
            <CardBody>
              <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed">
                {ACCOUNTS.map((line) => <li key={line}>{line}</li>)}
              </ul>
            </CardBody>
          </Card>
        ) : null}
      </div>
    </Page>
  )
}
