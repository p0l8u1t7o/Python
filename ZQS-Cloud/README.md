# ZQS Cloud

分散式能源設備的伺服器端控制與資料平台：設備註冊、遙測接收、時序資料儲存、告警、
下行控制，以及表後（BTM）儲能管理。

通訊採用 **Eclipse Sparkplug B**（MQTT namespace `spBv1.0`，protobuf payload），
所以照規範實作的設備也能接上其他 Sparkplug 主機，不會被綁在這個平台上。完整契約見
[docs/device-protocol.html](docs/device-protocol.html)——第一個預期的客戶端是 LabVIEW
實作，該文件第 9 節有 protobuf 在 LabVIEW 端的三條可行路線。LabVIEW 也可以直接啟動
與停止這些服務，見 [docs/labview-integration.html](docs/labview-integration.html)。

設備端開發者不需要架 broker 就能驗證自己的客戶端。一行指令，不必先啟用任何東西：

```powershell
.\scripts\test-device.ps1
```

它會先證明測試工具本身是可信的——一台正確的參考設備必須通過，數台刻意做錯的設備
必須各自被抓出來——然後等待你的實體設備連上並印出驗收報告。每一項判定都來自平台
自己的認證、ACL 與 payload 程式碼。詳見
[docs/device-test-harness.html](docs/device-test-harness.html)。

---

## 系統架構

```
                     ┌──────────────┐
  edge nodes ─NDATA─▶│     EMQX     │◀──DCMD── control commands
  (gateways)         └──────┬───────┘              ▲
                            │ subscribe            │ publish
                            ▼                      │
                     ┌──────────────┐        ┌─────┴──────┐
                     │   ingestor   │        │  Django    │
                     │ decode +     │        │  Ninja API │◀── React console
                     │ enqueue      │        └─────┬──────┘
                     └──────┬───────┘              │
                            │                      │
                     ┌──────▼───────┐              │
                     │ Redis Streams│              │
                     │  (or AMQP)   │              │
                     └──────┬───────┘              │
                            │                      │
                     ┌──────▼───────┐              │
                     │    worker    │              │
                     │ batch write  │              │
                     │ rule engine  │              │
                     │ notify       │              │
                     └──────┬───────┘              │
                            ▼                      ▼
                     ┌───────────────────────────────┐
                     │  SQLite / PostgreSQL(Timescale)│
                     └───────────────────────────────┘
```

這個切分是刻意的：**ingestor 完全不碰資料庫**。資料庫變慢或被鎖住不會拖垮 MQTT
的消費速度，而佇列會吸收掉那些原本會在 broker 端被丟棄的突發流量。

| 元件 | 進入點 | 擴充方式 |
| --- | --- | --- |
| API | `gunicorn config.wsgi` | 放在負載平衡後面加副本 |
| Ingestor | `manage.py run_ingestor` | 加副本（EMQX shared subscription） |
| Worker | `manage.py run_worker` | 加副本（同一個 consumer group） |
| Scheduler | `manage.py run_scheduler` | **只跑一個實例** |
| Workflows | `manage.py run_workflows` | **只跑一個實例**（tick 預設 2 秒，是所有流程計時器的解析度） |

開發時另有兩個只給本機用的行程，讓上面這條鏈路不必安裝任何東西就能跑起來：
`manage.py run_broker`（內建 MQTT broker）與 `manage.py run_pipeline`
（ingestor + worker 同行程）。兩者都不可用於正式環境，理由見下方「快速開始」。

---

## 快速開始

一行指令做完所有事並啟動——API、console、示範租戶，還有三天份可以看的 telemetry：

```powershell
.\scripts\dev.ps1 -Setup          # Windows
```

```bash
./scripts/dev.sh --setup          # Linux, macOS, WSL, Git Bash
```

之後用 `.\scripts\dev.ps1`（或 `./scripts/dev.sh`）啟動，用 `.\scripts\stop.ps1`
（或 Ctrl-C）停止。

| | |
| --- | --- |
| Console | <http://127.0.0.1:5173> |
| API 文件 | <http://127.0.0.1:8000/api/docs> |
| MQTT | `mqtt://127.0.0.1:1883`（內建開發用 broker） |
| 登入 | `admin@example.com` / `ChangeMe-2026!` |

**預設就是完整的即時路徑**，不需要 Docker、不需要 Redis、不需要 EMQX。啟動腳本會
一併帶起：

| 行程 | 做什麼 |
| --- | --- |
| `zqs-broker` | 內建的開發用 MQTT broker（[amqtt](https://github.com/Yakifo/amqtt)） |
| `zqs-pipeline` | ingestor + worker 在同一個行程，共用記憶體匯流排 |

啟動後所有登記的設備都是**離線**的；開 `.\scripts\sim-console.ps1`、按「全部上線」，登記的閘道器與設備就以真實 MQTT 客戶端上線並持續發布 telemetry。

> **內建 broker 只能用在開發。** 它是匿名的、沒有 ACL、不呼叫平台的 auth/ACL
> webhook——換句話說 `deploy/emqx/README.md` 描述的設備身分模型它**一項都沒有
> 執行**。它也不支援 shared subscription（所以只能跑一個 ingestor）、不做持久化。
> 每一項都是正式環境要用 EMQX 的理由。

### 旗標

| 旗標 | 作用 |
| --- | --- |
| `-Full` / `--full` | 改用真正的 EMQX 與 Redis，ingestor 與 worker 分開跑（正式環境的形狀） |
| `-NoBroker` / `--no-broker` | 完全不要即時路徑，只跑 console 與 API |

`-Full` 需要先把服務起來：

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
docker run -d --name emqx -p 1883:1883 -p 18083:18083 emqx/emqx:5.8
```

這個模式一定要 Redis：ingestor 與 worker 是兩個獨立行程，記憶體匯流排接不起來。
若 1883 已經有東西在聽（例如你自己起的 EMQX），啟動腳本會直接用它，不會硬搶連接埠。

完整細節、逐一下指令的作法與疑難排解在
**[docs/running-locally.html](docs/running-locally.html)**。版本驗證範圍與已知限制見 **[docs/release-notes.html](docs/release-notes.html)**。文件入口：`docs/index.html`（含專有名詞解釋與技術原理）。畫布式控制流程的架構、所有物件類別、踩過的坑與移植步驟見 **[docs/workflow-design.html](docs/workflow-design.html)**；客戶展示流程見 **[docs/demo-guide.html](docs/demo-guide.html)**。

## 快速開始（Docker）

```bash
copy .env.example .env
docker compose up -d
docker compose exec api python manage.py seed_demo
```

然後設定 EMQX 的 auth/ACL webhook，見
[deploy/emqx/README.md](deploy/emqx/README.md)。

---

## 設定

一切都由環境變數驅動，完整清單與預設值見 [.env.example](.env.example)。值得知道的
幾個選擇：

| 變數 | 選項 | 說明 |
| --- | --- | --- |
| `DB_ENGINE` | `sqlite`, `postgres`, `timescale` | 預設 SQLite，足以跑完整套系統；要撐規模再換 |
| `BUS_BACKEND` | `redis`, `rabbitmq`, `memory` | 預設 Redis Streams；`rabbitmq` 用 pika（已含在 `requirements.txt`） |
| `CACHE_BACKEND` | `locmem`, `redis` | API 一旦跑超過一個副本就要換成 `redis`，速率限制才會共用 |
| `MQTT_ENABLED` | `1`, `0` | `0` 代表這個部署刻意不接 broker。即時擷取與下行命令不可用，健康檢查顯示「未使用」而不是報連線失敗 |
| `MQTT_PROTOCOL_VERSION` | `5`, `311` | EMQX 兩種都支援。內建的開發用 broker 只講 3.1.1，啟動腳本會自動設成 `311` |
| `MQTT_USE_SHARED_SUBSCRIPTION` | `1`, `0` | `1` 才能擴充 ingestor；`0` 給單一實例搭配 persistent session |
| `INGEST_AUTO_PROVISION` | `0`, `1` | `1` 會在未知設備第一次上行時自動註冊 |
| `EMQX_WEBHOOK_TOKEN` | 任意密鑰 | 留空等於關閉 broker webhook |

### 更換資料庫

應用程式碼裡沒有任何 SQLite 專屬的東西。所有非純 ORM 的 SQL 都集中在
[apps/telemetry/repository.py](apps/telemetry/repository.py)，它只在兩個
engine-specific 的操作（時間分桶與 latest-value upsert）上依 `connection.vendor`
分岔。

要換到 PostgreSQL：設定 `DB_ENGINE=postgres` 與連線憑證（psycopg 已含在 `requirements.txt`）、跑 `migrate`。要用 TimescaleDB 不需要額外旗標（依連線自動偵測），只要把 sample 表轉成 hypertable：

```sql
SELECT create_hypertable('telemetry_sample', 'ts', migrate_data => true);
```

---

## 功能對照

| 需求 | 在哪裡 |
| --- | --- |
| 帳號與權限管理 | `apps/accounts` —— 使用者、組織、4 種角色、API key、帶 refresh rotation 的 JWT |
| 權限綁場域（只能看某廠） | `Membership.sites` —— 空清單代表整個組織；指定一個場域等於連同其子樹 |
| 通訊協定 | **Eclipse Sparkplug B**（`spBv1.0`，protobuf）——三層位址、生死流程、序號與別名、重生復原。見 [docs/device-protocol.html](docs/device-protocol.html) |
| 網關（一條連線帶多台設備） | `EdgeNode` —— MQTT 憑證掛在節點上；設備自己直連時會自動取得一個隱含節點 |
| 設備能力與命令安全 | `apps/devices` —— 能力旗標、命令閘門、設備宣告（[docs/system-logic.html](docs/system-logic.html)） |
| 多設備狀態與登記名稱 | `apps/devices` —— 註冊表、連線狀態、`GET /api/devices` |
| 變更設備的登記場域 | `PATCH /api/devices/{id}` —— 一台設備只能登記一個場域；場域下還有設備時不允許刪除。能源資產綁定會跟著設備一起搬 |
| 設備序號不可重複 | 組織內唯一（空白除外），衝突時回 409 並指出是哪一台設備已經在用 |
| 設備投入成本 | `Device.capital_cost` 等欄位 + `GET /api/ems/sites/{id}/investment`；電池的循環成本可由採購價自動換算 |
| 個人化的介面設定 | `UserPreference` + `/api/auth/me/ui/{key}` —— 即時數值的挑選與排序、總覽檢視、設備清單版面，都跟著帳號走 |
| 依廠區、車間、產線分群 | `apps/devices` —— 巢狀場域，`GET /api/sites/{id}/summary` 會把子樹加總 |
| 設備在地圖上的位置 | `GET /api/devices/map` —— 設備回報的 GPS，沒有就退回場域地址 |
| 選擇要記錄哪些時序 | `apps/telemetry` —— recording policy，可逐 metric 設定間隔、死區、心跳與保存期 |
| 個別設備耗能 | `GET /api/devices/{id}/energy` —— 有累計值就取差值，沒有就對功率積分並回報涵蓋率 |
| 運轉 session（最後一次充放電） | `apps/ems/sessions.py` + `GET /api/ems/sessions` —— 排程回算，帶遲滯與最短時長 |
| 設備告警與操作紀錄 | `apps/devices` events、`apps/alerts` alerts、`apps/audit` 操作軌跡；通知管道支援 Email／LINE 機器人／Webhook／MQTT，可分別訂閱規則警報（依嚴重度）與設備事件（依層級） |
| 淺色／深色主題 | 存在使用者帳號上（`PATCH /api/auth/me/preferences`），由 console 套用 |
| 多語系（en / zh-Hant / zh-Hans） | 使用者偏好 + 翻譯過的 metric 標籤 + `Accept-Language` |
| 表後儲能管理 | `apps/ems` —— 資產角色、儲能方案、時間電價、15 分鐘能源區間、節費；儲能規劃為具名模板（`/ems/plans`，場域綁定制）；策略引擎（契約容量管理／TOU 套利／自發自用／備援保留／工作流程接管）、需量反應事件（`POST /api/ems/sites/{id}/demand-response`）、電池健康約束（日循環上限、溫度閘門） |
| 電價方案 CRUD | `GET/POST/PUT/DELETE /api/ems/tariffs`，console 的 `/tariffs` 頁；內建台電時間電價方案一鍵套用（`GET /api/ems/tariffs/presets`，牌價內建、標注費率年度，台電無即時電價 API） |
| 多來源成本模型 | `apps/ems/costs/` —— 註冊表式，新增設備類型不必改結算核心 |
| 報表幣別 | `Organization.reporting_currency` —— 一個組織一種；沒有電價方案的場域退回它，幣別不符的方案在儲存時就擋（`currency_mismatch`）|
| 即插即用 | DBIRTH 帶著單位與資料型別，沒設定過的 metric 會自動建進目錄，圖表一上來就有標籤（`apps/telemetry/autoregister.py`）|
| 設備事件查詢 | `GET /api/events` —— 全機隊的事件紀錄，可依場域、等級、代碼與全文搜尋，console 的 `/events` 頁 |
| 設備商整合說明 | console 的 `/integration` 頁 —— 把這個環境的 group、host id 與 topic 直接填好給設備開發人員 |
| 地址轉座標 | 新增場域時可用地址查詢座標（OpenStreetMap Nominatim，免費免金鑰）；查不到就手動輸入 |
| 自動調度 | `apps/ems/dispatch.py` —— 把 `DispatchWindow` 變成實際命令，並強制執行運轉限制 |
| 工作流程 | `apps/workflows` —— React Flow 畫布畫控制邏輯：IF、計時、時間區間、等待、條件等待、命令、跳轉、並行分支、Note 註解；拖曳加入、Delete／Ctrl+C／Ctrl+V／Ctrl+Z；執行控制列（暫停／繼續／停止／單步／停止點／節點間延遲）、參數防呆、自動排列、離開未存提醒；每租戶並行上限由伺服器鎖定（預設 5）；儲能規劃可指定流程接管調度 |

---

## API

Base path `/api`。DEBUG 模式下 `/api/docs` 有完整的互動式文件。

**認證。** 使用者 token 或機器金鑰擇一：

```http
Authorization: Bearer <access_token>
Authorization: ApiKey zqs_<prefix>.<secret>
```

隸屬多個組織的使用者用 `X-Organization: <slug>` 指定；只有一個時可以省略。

**錯誤**格式一致，帶一個穩定的 `code`，由 console 對應到翻譯後的訊息：

```json
{"error": {"code": "parameter_out_of_range", "message": "...", "details": {...}}}
```

### 主要端點

| Method | Path | 用途 |
| --- | --- | --- |
| `POST` | `/auth/login`, `/auth/refresh`, `/auth/logout` | session 生命週期 |
| `GET` | `/auth/me` | 個人資料、角色、有效權限、場域範圍 |
| `PATCH` | `/auth/me/preferences` | 主題、語言、時區（後端自己會讀的偏好） |
| `GET/PUT/DELETE` | `/auth/me/ui/{key}` | 純介面版面設定（後端只存不讀） |
| `PATCH` | `/members/{id}` | 角色與場域權限（`site_ids` 省略時不動原設定） |
| `GET/POST` | `/sites` | 場域註冊表；`?include_descendants=1` 會附上子樹合計 |
| `GET` | `/sites/{id}/summary` | 一個場域與其子樹的設備、告警與能源 |
| `GET` | `/events` | 全機隊事件紀錄（場域、等級、代碼、全文搜尋） |
| `GET` | `/events/codes` | 這段期間實際出現過的事件代碼，供篩選用 |
| `GET` | `/sites/geocode` | 地址轉座標；查不到就回空清單，不是錯誤 |
| `GET` | `/system/timezones` | 這台伺服器認得的 IANA 時區，供下拉選單用 |
| `GET/POST` | `/edge-nodes` | 網關註冊表（建立時會回傳一次 MQTT 憑證） |
| `POST` | `/edge-nodes/{id}/credential` | 輪替節點憑證（舊密碼立即失效） |
| `POST` | `/edge-nodes/{id}/rebirth` | 要求節點重新宣告所有 metric |
| `GET/POST` | `/devices` | 設備註冊表（省略 `edge_node_id` 會自動建立隱含節點並回傳一次憑證） |
| `PATCH` | `/devices/{id}` | 修改登記名稱、登記場域、藍圖等 |
| `GET` | `/devices/{id}/energy` | 單一設備的耗能，含判定依據與涵蓋率 |
| `POST` | `/devices/{id}/lifecycle` | 暫停、除役、拒絕或恢復服務 |
| `POST` | `/devices/{id}/replace` | 登記後繼設備並把所有綁定移轉過去 |
| `GET` | `/devices/map` | 地圖標記，帶告警嚴重度 |
| `GET` | `/devices/{id}` | 詳情，含最新值與可用命令 |
| `POST` | `/devices/{id}/commands` | **下行控制** |
| `GET` | `/devices/{id}/events` | 設備自己回報的操作紀錄 |
| `GET` | `/blueprints` | 設備型號與其命令目錄 |
| `GET/POST` | `/metrics` | metric 目錄 |
| `GET/POST/PUT` | `/recording-policies` | 記錄哪些時序、怎麼記 |
| `POST` | `/telemetry/series` | 時序查詢，會自動降採樣 |
| `GET` | `/telemetry/latest` | 當前值 |
| `GET/POST/PUT` | `/alert-rules` | 門檻規則 |
| `GET` | `/alerts`, `/alerts/summary` | 告警生命週期 |
| `POST` | `/alerts/{id}/acknowledge`, `/resolve` | 操作員動作 |
| `GET` | `/audit` | 操作稽核軌跡 |
| `GET` | `/ems/sites/{id}/overview` | 即時 BTM 功率流 + 今日能源 |
| `GET` | `/ems/sites/{id}/summary` | 能源、成本、節費、自用率 |
| `GET` | `/ems/sites/{id}/cost-breakdown` | 各來源成本分項（市電／電池／發電機） |
| `GET` | `/ems/live` | 一次取得所有場域的即時功率、SOC 與今日數字 |
| `GET` | `/ems/sites/{id}/investment` | 該場域的設備採購成本與年度攤提 |
| `GET` | `/ems/cost-overview` | 一次取得所有場域的電費與節費 |
| `GET/PUT` | `/ems/sites/{id}/plan` | 儲能策略與運轉限制 |
| `GET/POST/PUT/DELETE` | `/ems/tariffs` | 電價方案 |
| `GET` | `/ems/cost-models` | 已註冊的成本模型 |
| `GET` | `/ems/sessions`, `/ems/sessions/summary` | 運轉 session |
| `POST` | `/ems/sessions/rebuild` | 手動重算 session |
| `GET` | `/ems/dispatch-windows/preview` | 調度引擎此刻會下什麼命令，以及為什麼 |
| `POST` | `/ems/dispatch-windows/run` | 立即執行調度（`?dry_run=1` 只預覽） |
| `GET` | `/system/health`, `/system/capabilities` | 探針與 SPA 啟動設定 |

---

## 維運

```bash
python manage.py bootstrap --update-existing   # 更新內建目錄
python manage.py generate_history --days 3     # 回補示範 telemetry
python manage.py aggregate_energy --hours 2    # 重算 BTM 能源區間
python manage.py rebuild_sessions --hours 2    # 重算運轉 session
python manage.py run_dispatch --dry-run        # 看調度引擎會下什麼命令
python manage.py build_rollups --interval 900  # 圖表用的聚合桶
python manage.py prune_telemetry --dry-run     # 保存期預覽
python manage.py createsuperuser               # 平台管理員

# 只給開發用：
python manage.py run_broker                    # 內建 MQTT broker
python manage.py run_pipeline                  # ingestor + worker 同行程
```

`aggregate_energy`、`rebuild_sessions`、`build_rollups` 與 `run_dispatch` 建議每
5 分鐘跑一次，`prune_telemetry` 每天一次。`docker-compose.yml` 裡的 `scheduler`
服務已經照做；`python manage.py run_scheduler` 是同一個迴圈的單行程版本，給沒有
cron 也沒有 shell 的主機用。

> 調度引擎會對實體硬體送出真正的命令。`run_scheduler --no-dispatch` 可以在只想
> 要聚合與 session 回算時把它關掉。

### 從 LabVIEW 使用

`services/labview/labview_api.py` 讓 LabVIEW 的 Python Node 監管這四個服務：
非阻塞的啟動與停止、可輪詢的整數狀態碼、輸出導到 log 檔。見
[docs/labview-integration.html](docs/labview-integration.html)。

### 健康檢查

`GET /healthz` 是存活探針，刻意不碰資料庫。`GET /api/system/health` 是就緒探針，
會分別回報每個相依元件（資料庫、訊息匯流排、MQTT）。

---

## 測試

```bash
python manage.py test tests
python -m ruff check apps/ services/ tests/
cd frontend && npm run typecheck
cd frontend && npm run e2e     # 需要後端先跑著
```

611 個後端測試，涵蓋：ingest pipeline 的端到端路徑（payload → bus → worker →
資料庫）、告警引擎的時序與遲滯行為、recording policy 的解析與死區閘門、EMS 能源
積分與電價解析、成本模型註冊表與「設備宣告不得影響帳單」的信任邊界、運轉 session
的遲滯與資料中斷處理、調度引擎與運轉限制的強制執行、場域權限（含「空清單代表整個
組織」與子樹展開）、API 的認證／RBAC／租戶隔離／稽核軌跡、LabVIEW 監管器的行程
狀態機、場域樹的循環防護與 roll-up 算術、設備能力閘門，以及避免同一段時間被兩台
設備重複計算的更換規則，以及這一輪新增的：序號唯一性、能源資產隨設備搬遷、
「未使用的相依元件不是故障」的健康判定、每位使用者的介面版面儲存、設備成本與
年度攤提、開發用執行環境（內建 broker、同行程 pipeline 的匯流排共用、MQTT 協定
版本切換）、報表幣別（沒有電價方案的場域退回組織幣別、跨場域不一致仍回空字串、
幣別不符的電價方案在儲存時被拒）、即插即用的 metric 註冊（不覆蓋既有定義、不遮蔽
內建 metric、註冊不等於授權）、全機隊事件紀錄的篩選與場域權限、地址查詢的每一種
失敗都退回手動輸入，以及整套 Sparkplug B：protobuf 的有號整數與
null 往返、topic 文法與訂閱萬用字元、別名解析與整表覆寫、`bdSeq` 讓過期的遺言
不會打死剛重連的節點、序號缺號與未知別名都會觸發重生要求。

另有 36 個 Playwright 瀏覽器測試（`frontend/e2e/`），跑遍每條路由 × 三種語言，
斷言 console 沒有任何錯誤、沒有未翻譯的 key，並涵蓋拖曳排序、地圖、彈出層、儲能
規劃的選項卡、事件紀錄篩選、時區下拉這些只有真瀏覽器測得出來的部分。`tsc` 證明型別對得上，但不會執行任何一行 render。

---

## 專案結構

```
apps/
  accounts/    使用者、組織、角色、API key、JWT
  core/        base model、錯誤、logging、throttle、時間處理
  devices/     場域、藍圖、邊緣節點、設備、憑證、別名表、命令、EMQX webhook
  telemetry/   metric 目錄與自動註冊、recording policy、樣本、rollup、查詢、單機耗能
  alerts/      門檻規則、告警生命週期、通知管道
  audit/       操作稽核軌跡
  ems/         表後資產、儲能方案、電價、能源區間、成本模型、運轉 session、調度
    costs/     可註冊的成本模型（市電／電池循環／柴發油耗）
services/
  bus/         訊息匯流排抽象（Redis Streams / RabbitMQ / in-memory）
  sparkplug/   Sparkplug B：proto schema、topic 文法、編解碼、metric profile、節點用戶端
  mqtt/        自動重連客戶端、下行發布器
  ingestor/    Sparkplug 主機應用：訂閱、解碼、入列，並發布自己的 STATE
  worker/      佇列消費者：寫入、判定、通知、維護
  harness/     設備測試工具（broker、模擬器、驗收檢查）
  labview/     給 LabVIEW Python Node 用的非阻塞行程控制
config/        設定、API 組裝、URL
frontend/      React console（見 frontend/README.md）
scripts/       dev.ps1 / dev.sh 啟動器、stop.ps1、reset-demo.ps1（展示租戶）、sim-console.ps1、test-device.ps1
docs/          HTML 文件：index.html 為入口（設備協定、系統邏輯、本機開發、LabVIEW 整合、程式碼導覽、工作流程引擎設計手冊、客戶展示指南、專有名詞解釋、技術原理、發行說明）
deploy/        EMQX 設定說明
tests/         測試套件
```

---

## 前端

React console 位於 [frontend/](frontend/)，有自己的
[README](frontend/README.md)。

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173，會把 /api 代理到 :8000
```

Vite 6 + React 19 + TypeScript（strict），伺服器狀態用 TanStack Query，樣式用
Tailwind 4，時序圖與能源平衡用 Recharts，地圖用 Leaflet，多語系用 i18next
（English / 繁體中文 / 简体中文）。

| 路由 | 做什麼 |
| --- | --- |
| `/` | 兩種可切換的檢視（會記住偏好）：「能源」是即時功率四宮格 + SOC 錶 + 各場域狀態表 + 電費節費圖表；「機隊」是設備計數、未結告警、場域彙總與相依健康 |
| `/devices`, `/devices/:id` | 註冊表（帶類型 ICON、說明欄，可切換列表／卡片）、即時值（可自由增刪與拖曳排序，設定跟著帳號走）、歷史、命令、設備紀錄、連線歷史、單機耗能、運轉 session；可編輯登記名稱、登記場域與設備成本 |
| `/map` | 上方全台場域圖（圓圈大小＝設備數），下方該場域的設備分布圖，兩張都可縮放 |
| `/alerts` | 嚴重度篩選、批次確認、告警時間軸 |
| `/storage` | 表後：即時功率流、能源平衡、SOC、成本與節費、各來源成本分項、運轉 session、調度預覽；時間區間可自訂 |
| `/telemetry` | 挑設備 × metric、畫圖、匯出 CSV、metric 目錄 |
| `/tariffs` | 電價方案的新增／編輯／刪除，含時間電價時段編輯器 |
| `/sites`, `/recording`, `/rules` | 場域、recording policy、告警規則編輯器 |
| `/audit`, `/settings` | 稽核軌跡；個人資料、外觀、成員與場域權限、API key |
| `/help` | 上手步驟、每頁用途、設備類型解說、名詞解釋、常見問題，以及這個環境實際跑著什麼 |

所有場域下拉選單都是樹狀選擇器，可展開／收合並支援搜尋——搜尋時會一併保留符合項目
的上層節點，因為「產線 3」離開它所屬的廠區就沒有意義了。

介面版面（總覽檢視、設備清單版面、每台設備的即時數值挑選與排序）存在使用者帳號上，
而不是瀏覽器的 localStorage：存在 localStorage 的版面，換一台電腦就要重排一次。
