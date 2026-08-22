# ZQS Cloud console

ZQS Cloud 能源設備平台的 React 前端。

## 技術選擇

| 面向 | 選擇 | 理由 |
| --- | --- | --- |
| 建置 | Vite 6 + TypeScript (strict) | 開發伺服器快，API 介面有型別 |
| UI | React 19 | — |
| 路由 | React Router 7 | 巢狀 layout route、lazy route chunk |
| 伺服器狀態 | TanStack Query 5 | 快取、背景重取、失效控制 |
| 樣式 | Tailwind CSS 4 | 語意化 token 定義在 `src/index.css` |
| 圖表 | Recharts | 時序圖、堆疊能源平衡圖、成本長條圖 |
| 地圖 | Leaflet + react-leaflet | OpenStreetMap 圖磚，不需要 API key |
| i18n | i18next | English、繁體中文、简体中文 |

## 執行

```bash
npm install
npm run dev          # http://127.0.0.1:5173
```

開發伺服器會把 `/api` 代理到 `http://127.0.0.1:8000`，所以要同時跑 Django API。
要指到別的位址用 `VITE_PROXY_TARGET`；要對絕對 API origin 建置用
`VITE_API_BASE_URL`。

```bash
npm run build        # tsc -b && vite build  ->  dist/
npm run typecheck
npm run preview
npm run e2e          # Playwright，需要後端先跑著
npm run e2e:ui       # 同上，開互動式檢視器
```

E2E 用系統已安裝的 Chrome（`channel: 'chrome'`），不下載自己的瀏覽器。後端請先用
`scripts/dev.ps1` 起來；Vite 由 Playwright 自己管理。

## 目錄結構

```
src/
  lib/
    api.ts          fetch 客戶端：token 儲存、single-flight refresh、組織標頭
    types.ts        API 回應型別，對應 Ninja schema
    queries.ts      所有 TanStack Query hook，依資源分 key
    errors.ts       API error code -> 翻譯後的句子
    format.ts       依語系的數字、單位、日期、時長格式化
    useTimeRange.ts 錨定的時間視窗，另支援使用者自訂的固定區間
  i18n/             設定 + 三個語系檔（en 是 key 的型別來源）
  providers/        Theme、Auth、Toast
  components/
    layout/         AppShell、Sidebar、TopBar
    ui/             Button、Card、Badge、Field、Table、Modal、StatTile、狀態元件
                    SiteTreeSelect（樹狀場域選擇器）、DeviceIcon、TimeRangePicker
                    MetricPicker（挑選並排序即時數值）
    charts/         TimeSeriesChart、EnergyCharts、CostCharts、PowerGauge、
                    PowerFlowDiagram
  pages/            一個路由一個檔案
public/             favicon.ico、logo.png（原始檔在專案根目錄的 Image/）
e2e/                Playwright 測試
  auth.setup.ts     登入一次，之後所有測試共用 session
  helpers.ts        console 攔截、未翻譯 key 偵測、截圖
  smoke.spec.ts     每條路由 × 每種語言都能開，且 console 乾淨
  interactions.spec.ts  拖曳、地圖、彈出層等只有真瀏覽器測得出來的部分
```

## 幾個容易做錯的地方

**Token refresh 是 single-flight。** 儀表板一次會送出五六個查詢；如果每個在收到
401 時各自去 refresh，就會燒掉六張 refresh token 並觸發伺服器的重用偵測，把使用者
登出。`api.ts` 讓所有等待者共用同一個 refresh promise。

**主題在第一次繪製前就套用。** `index.html` 裡有一小段 inline script 讀取儲存的
偏好並設定 `dark` class，所以 React 啟動期間不會閃過錯的配色。這個偏好也會存到
使用者帳號上，換一台瀏覽器仍然跟著走。

**圖表讀的是實際色值，不是 CSS 變數。** SVG 的 presentation attribute 不接受
`var(--x)`，所以 `chartTheme.ts` 用 `getComputedStyle` 解析出調色盤，並在主題切換
時重新解析。

**圖上的空缺要保持是空缺。** 各序列被合併到同一條時間軸上，缺樣本處填 `null` 並
搭配 `connectNulls={false}`，所以斷線畫出來是斷開的，而不是一條假裝有資料的直線。

**Tailwind 只看得到字面上的 class 字串。** 像 `` `text-${align}` `` 這種永遠不會被
產生出來；table 元件因此改成對應到真正的 class 名稱。

**時間視窗是錨定的。** `useTimeRange` 只在區間改變或呼叫 `refresh()` 時重算
`start`/`end`。每次 render 都重算會讓 query key 不斷改變，於是永遠重取。使用者自訂
的固定區間則完全不漂移——這正是它存在的理由：對照事故報告時，座標軸必須站著不動。

**樹狀場域選擇器在搜尋時會保留上層節點。** 只顯示命中的節點會把「產線 3」畫在最上
層，那是對它實際位置的謊言。

**介面版面存在帳號上，不是 localStorage。** 總覽的檢視、設備清單的列表／卡片、每台
設備的即時數值挑選與排序，都走 `useUiPreference()` → `/auth/me/ui/{key}`。存在
localStorage 的版面，換一台電腦就要重排一次；而這正是「記住用戶喜好」要解決的事。

和 `User` 上的 `theme` / `language` / `timezone_name` 不同：那三個後端自己會讀，
每個客戶端都必須遵守；這些後端只存不讀。

**console 必須是乾淨的，所以預期中的 404 要列白名單。** 瀏覽器不管應用程式預不預期
都會把 4xx 記進 console。`/devices/{id}/declaration` 在設備從未宣告時回 404 是設計
如此（`useDeviceDeclaration` 的註解寫明了），`e2e/helpers.ts` 的 `EXPECTED_404` 把
它跟真正的錯誤分開。列白名單而不是放寬斷言——放寬了就再也抓不到新的 404。

**E2E 只登入一次。** 登入限流是 10 次／5 分鐘。每個測試各登入一次，第 11 個開始會
全部變成跟被測程式無關的噪音。

**即時數值預設全部顯示。** 沒有存過版面時，顯示設備回報的**每一項**。這是誠實的
預設值——另一個選項是猜一組「有用的」子集，而那會藏起某些人裝這台設備就是為了看的
讀值。

## 功能對照

| 需求 | 在哪裡 |
| --- | --- |
| 帳號與權限管理 | `pages/SettingsPage.tsx` —— 成員、角色、場域權限、API key、密碼 |
| 多設備狀態與登記名稱 | `pages/DevicesPage.tsx`、`DeviceDetailPage.tsx` |
| 變更登記場域／修改登記名稱 | `DeviceDetailPage.tsx` 的編輯對話框 |
| 依設備類型顯示 ICON | `components/ui/DeviceIcon.tsx` —— 依 category，不依藍圖 |
| 設備在地圖上的位置 | `pages/MapPage.tsx` —— 場域總覽圖 + 單一場域設備圖 |
| 選擇要記錄哪些時序 | `pages/RecordingPage.tsx` —— 間隔、死區、心跳、保存期 |
| 設備告警與操作紀錄 | `pages/AlertsPage.tsx`、設備紀錄分頁、`pages/AuditPage.tsx` |
| 淺色／深色主題 | `providers/ThemeProvider.tsx`，可在頂欄與設定頁切換 |
| 多語系 | `i18n/`，可在登入畫面與頂欄切換 |
| 表後儲能管理 | `pages/StoragePage.tsx` + `components/charts/` |
| 電價方案管理 | `pages/TariffsPage.tsx` |
| 各場域電費與節費視覺化 | `pages/DashboardPage.tsx` + `components/charts/CostCharts.tsx` |
| 自訂顯示時間區間 | `components/ui/TimeRangePicker.tsx` + `lib/useTimeRange.ts` |
| 樹狀場域下拉選單 | `components/ui/SiteTreeSelect.tsx` |
| 設備清單列表／卡片切換 | `pages/DevicesPage.tsx`，偏好存在帳號上 |
| 即時數值自由增刪與排序 | `components/ui/MetricPicker.tsx` —— 原生 HTML5 拖曳，另有上下按鈕給鍵盤使用者 |
| 總覽的能源／機隊雙檢視 | `pages/DashboardPage.tsx` + `components/charts/PowerGauge.tsx` |
| 設備成本輸入與年度攤提 | `DeviceDetailPage.tsx` 的編輯對話框；場域彙總在 `StoragePage.tsx` |
| 設備類型解說 | `DevicesPage.tsx` 的 `BlueprintPicker` + i18n 的 `devices.categoryHelp` |
| 幫助頁 | `pages/HelpPage.tsx` —— 上手步驟、每頁用途、名詞解釋、常見問題、環境資訊 |

## 部署

`npm run build` 會產生靜態的 `dist/`。放到任何靜態主機上並讓
`VITE_API_BASE_URL` 指向 API；或者放在同一個 origin 下、由反向代理把 `/api` 轉給
Django——這樣就不需要任何環境變數。

router 用的是 history mode，所以主機必須把不認得的路徑改寫到 `index.html`。
