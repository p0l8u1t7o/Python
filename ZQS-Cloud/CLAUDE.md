# CLAUDE.md — ZQS-Cloud 開發須知

給在這個專案裡工作的 Claude（與人）看的備忘：怎麼跑、怎麼驗、哪些坑踩過。
系統設計與協定細節不在這裡，請看 `docs/`（`codebase-guide.html`、`system-logic.html`、`device-protocol.html`）。

## 回覆與文件語言

- 對話回覆、commit 訊息、文件一律**繁體中文**；程式碼、識別字、術語保持原文。
- 三個 locale 都要改：`frontend/src/i18n/locales/{zh-Hant,zh-Hans,en}.ts`，key 結構要一致。

## 專案形狀

- 後端 Django 5.1 + django-ninja（`apps/`、`services/`、`config/`），前端 React 19 / Vite / TypeScript / Tailwind v4（`frontend/`），設備協定 Sparkplug B over MQTT（`services/sparkplug/`），內建開發用 amqtt broker（`manage.py run_broker`，只支援 MQTT 3.1.1）。
- 設定全部走 `.env`（範本 `.env.example` 每個參數都有註解）；`config/settings/dev.py` 在 `BUS_BACKEND` 留空時用 memory bus。
- `ProtocalBufferPayload/` 已於 2026-08-26 刪除、不再維護；設備端 proto 只指向 `services/sparkplug/sparkplug_b.proto`，勿重建。

## Git

- **git 根目錄是上一層 `d:\Working Space\Python`**，不是 ZQS-Cloud。永遠只 `git add` ZQS-Cloud 底下的明確路徑，**不要 `git add -A` / `git add .`**（會把姊妹專案一起提交）。
- 一個需求一個 commit，訊息繁中，結尾 `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`。
- `Image/`、`.env*`、`frontend/e2e-results/` 都在 .gitignore。
- 使用者有時會自行 squash / 改寫歷史（commit 標題「暫時更新」），提交前先 `git log -3` 確認 HEAD。

## 啟動開發堆疊（Windows）

- 一鍵：`.\scripts\dev.ps1`（`-Setup` 第一次、`-Lan` 讓區網裝置連進來、`-Full` 用 EMQX+Redis）；停止 `.\scripts\stop.ps1`；模擬器 `.\scripts\sim-console.ps1`。
- 手動（Bash）時三個行程都要帶同一組環境變數：
  `BUS_BACKEND=memory MQTT_ENABLED=1 MQTT_PROTOCOL_VERSION=311 MQTT_USE_SHARED_SUBSCRIPTION=0`
  → `manage.py run_broker`、`manage.py runserver 127.0.0.1:8000 --noreload`、`manage.py run_pipeline`、`frontend: npm run dev`。
- **`runserver --noreload` 不會熱重載**：改了後端程式一定要重啟 API，否則會對著舊程式除錯。
- **只能有一個 `run_pipeline`**：memory bus 是行程內的，多開會讓每則封包被處理多次（同一筆資料出現重複的 ingest/worker 紀錄）。收工前用 `Get-CimInstance Win32_Process | Where CommandLine -like '*run_pipeline*'` 確認；PowerShell 的計數會把查詢用的 shell 自己也算進去，要看 Name 是 python.exe 的那些。
- 區網連不到時：先看 Wi-Fi 是不是被 Windows 歸為「公用」（會擋所有入站），再看防火牆規則；`dev.ps1 -Lan` 會印出對應指令。

## 驗證清單（改完就跑，報告要附實際結果）

- 後端：`.venv/Scripts/python.exe manage.py test --noinput`（約 840 項、90 s）、`python -m ruff check apps services`。
  - 測試 log 裡的 `database table is locked`（worker 通知執行緒 vs SQLite）是既有噪音，不是失敗；看最後的 `OK` / `FAILED`。
  - 開發堆疊跑著時不要跑測試（SQLite 會互鎖）。
- 前端：`npm run -s typecheck`（`frontend/`）。eslint 設定是舊版 `.eslintrc`，v9 CLI 直接跑會報設定錯誤，不要浪費時間。
- e2e：`npx playwright test`（`frontend/`）。需要 API + Vite 已啟動、`workers: 1`（共用同一個帳號的介面偏好）。全套約 12 分鐘，超過工具 10 分鐘上限時分兩批跑。只認 `*.spec.ts`；`*.script.ts`（截圖腳本）不會被收進去。**每次執行都會清空 `e2e-results/`**，要看的截圖先讀再跑下一批。
- 改了頁面就截圖看一眼（`page.screenshot` 或 `frontend/e2e/screenshots.script.ts` 產 `Image/`），排版問題肉眼最快。

## 前端慣例與踩過的坑

- `Card` / `CardBody` / `Tr` 不會把 `data-testid` 轉傳到 DOM：要 testid 就放在裡面的 `div` 上。
- `Button` 沒有 `variant="default"`，用 `secondary`；`Badge`/`StatTile` 的 tone 是 `neutral|brand|ok|info|warning|major|critical`（沒有 `warn`）。
- `/docs/...` 靜態文件不由 Vite / API 提供：頁面上引用文件時寫成純文字路徑，不要做成連結。
- three.js 場景一律 `lazy()` + `Suspense`，`WebGLRenderer` 建構失敗時呼叫 `onUnsupported` 退回 2D；資料經由 `ref` 進場景、用 signature 比對才重建；尊重 `prefers-reduced-motion`；cleanup 要 dispose geometry/material 並移除 canvas。範例：`components/charts/{EnergyScene3D,SiteScene3D,FleetScene3D}.tsx`。
- 會在掛載時 `scrollIntoView` 的元件會把整頁拉到它那裡（連線偵錯時間線踩過）：只在「有新列且不是第一次 render」時跟隨捲動。
- 頁面太長的處理方式：左右分欄 + `Tabs`（閘道器頁）、Modal 加 `size="xl"` 改雙欄（電價方案編輯）。
- 列表篩選用 URL search params（`?site=`、`?gateway=`），換篩選要把 offset 歸零。
- `Site` / `SiteLive` 都有 `parent_id`／`depth`：樹狀顯示自己用 `parent_id` 建樹，不要只靠 `depth` 縮排。

## 後端慣例與踩過的坑

- amqtt 外掛：class 內一定要有 `@dataclass class Config`，否則 amqtt **靜默不載入**；hook 方法命名 `on_<event>`；CONNECT 階段就被拒的連線（MQTT 5、will flag 缺 topic）不會進 hook，只有 `amqtt.broker` 的 WARNING，`services/harness/amqtt_trace.py` 用 logging handler 接。
- asyncio 行程（broker）裡**不能直接用 Django ORM**（SynchronousOnlyOperation）：用 `services/diagnostics.trace_bg()` 丟到背景執行緒。
- 連線偵錯 `services/diagnostics.py`：只在 `IngressDebug.enabled_until` 在未來時才寫，開關快取 5 s，寫入永遠 best-effort，每租戶保留 4000 列；新增拒收點時記得同時加 `diag.trace(...)`，診斷才說得出「卡在哪一步」。
- Sparkplug 規則（回答設備商問題時常用）：NBIRTH `seq=0` 且是連線後第一則；`bdSeq` 每次 CONNECT +1（重開機才歸零，TCP 重連歸零會讓晚到的舊遺言把節點打成離線）；NDEATH 只有 `bdSeq`、放在 CONNECT 的遺言；group_id = 租戶 slug；client id 慣例 `zqs:<node id>`；未登記的設備預設丟棄（`INGEST_AUTO_PROVISION=1` 才自動建檔並進待驗收）。
- `EdgeNode.birth_metrics` 在 NBIRTH 時照原樣保存宣告，只供閘道器頁顯示，平台行為看欄位（`bd_seq`、`firmware_version`…）。
- 場域樹的彙總（`_decorate_tree`）用一次分組查詢算全部場域，不要每列一查。
- 新增 migration 後跑 `manage.py makemigrations --check --dry-run` 確認沒漏。

## 環境／工具的坑

- Git Bash 的 heredoc 會吞掉反斜線與 `\{`：含反斜線或較長的腳本一律先用 Write 寫檔再執行。
- Windows PowerShell 5.1：沒有 `&&`／`||`、沒有三元運算子；`Stop-Process` 迴圈常以 exit 255 結束但其實已生效，之後再查一次行程確認。
- `.ps1` 檔要保留 UTF-8 BOM（用 `utf-8-sig` 讀寫），否則中文與符號會壞。
- 從 Bash 跑 `taskkill //F //PID <pid>`（雙斜線）。

## 改完要更新的文件

- `docs/release-notes.html`（每個功能一節）、`README.md` 功能表；協定相關改 `docs/device-protocol.html`；啟動／環境改 `docs/running-locally.html`；展示流程改 `docs/demo-guide.html`。
- 文件是靜態 HTML（含 TOC `<li>`），改標題時 id 與 TOC 要一起改。
