# 在本機執行 ZQS Cloud

兩種啟動方式：一支包辦所有事情的啟動腳本，或者想看清每個環節時，逐一下指令。

---

## 1. 一行指令

### Windows (PowerShell)

```powershell
cd "D:\Working Space\Python\ZQS-Cloud"
.\scripts\dev.ps1 -Setup
```

這會安裝 Python 與 Node 相依套件、遷移資料庫、建立示範租戶、回補三天的
telemetry，然後啟動**完整的即時路徑**並開啟瀏覽器：內建 MQTT broker、API、
ingestor + worker、console，以及三台模擬設備。

不需要 Docker、不需要 Redis、不需要 EMQX。

之後的日常使用：

```powershell
.\scripts\dev.ps1          # start
.\scripts\stop.ps1         # stop
```

每個服務各自跑在一個有標題的 PowerShell 視窗（`zqs-api`、`zqs-frontend`…），
方便閱讀各自的 log。`stop.ps1` 依啟動時寫下的 PID 檔關閉它們，並清掉任何殘留
的行程。

> 若 PowerShell 拒絕執行這支腳本，為目前使用者放行一次本機腳本：
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

### Linux, macOS, WSL, Git Bash

```bash
./scripts/dev.sh --setup   # first run
./scripts/dev.sh           # afterwards
```

全部在同一個終端機執行，輸出會加上前綴；Ctrl-C 停掉整組服務。

### 旗標

| 旗標 | 作用 |
| --- | --- |
| `-Setup` / `--setup` | 安裝、遷移、建立種子資料、回補歷史。可重複執行 |
| `-Full` / `--full` | 改用真正的 EMQX 與 Redis，ingestor 與 worker 分開跑（需要 Docker） |
| `-Simulate` / `--simulate` | 同 `-Full`，再加上模擬裝置 |
| `-NoBroker` / `--no-broker` | 完全不要即時路徑，只跑 console 與 API |
| `-HistoryDays` / `--history-days` | setup 時回補的天數（預設 3） |
| `-NoBrowser` | 不要開啟瀏覽器 |

### 啟動後有什麼

| | |
| --- | --- |
| Console | <http://127.0.0.1:5173> |
| API docs | <http://127.0.0.1:8000/api/docs> |
| MQTT | `mqtt://127.0.0.1:1883` — 內建開發用 broker |
| EMQX dashboard（`-Full`） | <http://127.0.0.1:18083> — admin / public |

以 `admin@example.com` / `ChangeMe-2026!` 登入。`operator@example.com` 與
`viewer@example.com` 使用相同密碼，適合用來看 UI 如何隨角色改變：operator 可以
下命令但不能註冊裝置；viewer 兩者都不行。

---

## 2. 三種模式，以及為什麼是三種

**預設 —— 完整的即時路徑，零外部相依。** 啟動腳本會帶起內建的開發用 MQTT
broker、API、ingestor + worker（同一個行程）、console，以及三台模擬設備。資料
真的會走完 MQTT → ingestor → queue → worker → 資料庫，所以畫面上的數值會跳、
設備是上線的、系統健康裡的 MQTT 是綠的。

兩個行程是專門為了這個模式存在的：

| 行程 | 為什麼要有它 |
| --- | --- |
| `manage.py run_broker` | 沒有它，唯一的選項是「裝 Docker 再拉 EMQX」。對只是想看看這套軟體的人來說太重了 |
| `manage.py run_pipeline` | `BUS_BACKEND=memory` 是**行程內**的 queue，兩個行程看不到彼此的訊息。把 ingestor 與 worker 放進同一個行程，就不必為了看資料而先裝 Redis |

> **這個 broker 只能用在開發。** 匿名、沒有 ACL、不呼叫平台的 auth/ACL
> webhook——`deploy/emqx/README.md` 描述的設備身分模型它**一項都沒有執行**。
> 也沒有 shared subscription、沒有持久化、沒有 metrics。每一項都是正式環境要用
> EMQX 的理由。

它只講 **MQTT 3.1.1**，所以啟動腳本在這個模式下會設 `MQTT_PROTOCOL_VERSION=311`
與 `MQTT_USE_SHARED_SUBSCRIPTION=0`。平台預設是 MQTT 5——它的 reason code 會說明
publish 為什麼被拒絕，3.1.1 只會說「被拒絕了」。

**`-Full` —— 換成正式環境的形狀。** 真正的 EMQX 與 Redis，ingestor 與 worker 分
開跑。需要 Docker：

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
docker run -d --name emqx -p 1883:1883 -p 18083:18083 emqx/emqx:5.8
```

這裡的 Redis 不是選配，理由同上。啟動腳本在此模式下會切換成
`BUS_BACKEND=redis`、`MQTT_PROTOCOL_VERSION=5`，且只要缺少其中一項服務就拒絕啟動。

若你已經自己在 1883 起了 EMQX，預設模式會**直接用它**而不是硬搶連接埠。

**`-NoBroker` —— 只要 console 與 API。** 沒有 broker、沒有 queue。每一頁都能用：
裝置註冊表、歷史圖表、儲能儀表板、alert、設定；*沒有*在跑的是即時擷取。系統健康
會把 MQTT 標成「未使用」而不是故障——它不是壞掉，是你叫它不要跑。

開發純前端版面時用這個最輕。

---

## 3. 示範資料

### 回補的歷史資料

```bash
python manage.py generate_history --days 3 --interval 120 --clear --with-faults
```

直接把過去 N 天的 telemetry 寫進資料庫——不經過 broker——再彙總成能源區間。
沒有這一步，儲能頁面與所有圖表一開始都是空的，因為 `simulate_device` 只會
產生*往後*的資料。

產生的場域依循種子資料中的儲能策略：辦公室負載尖峰接近 480 kW、400 kW 屋頂
PV，以及一組 500 kW / 1 MWh 電池，把需量削到 250 kW 的目標並在離峰時段補電。
因此儀表板上的數字，是由面對真實硬體時同一套 aggregator 算出來的，不是寫死的
數值。

| 旗標 | 作用 |
| --- | --- |
| `--days N` | 往前產生多少天（預設 3） |
| `--interval N` | 取樣間隔秒數（預設 60） |
| `--clear` | 先刪除該區間內的樣本、能源區間、event 與 alert |
| `--with-faults` | 注入異常，讓 alert 規則觸發、裝置記錄有內容 |
| `--no-alerts` | 跳過重播規則引擎 |
| `--site CODE` | 只限一個場域 |

`--with-faults` 還會留一段異常持續到「現在」，讓 alert 頁面有一筆未結案的
alert，而不是只有已解決的歷史。

回補同時會做兩件平常由 worker 負責的事：把裝置標記為曾經回報過（否則整個
機隊都顯示離線），並在產生的讀值上重播 alert 規則。

### 即時模擬

demo 資料裡的四台設備都掛在同一個網關（`ZQS-GW-0001`）底下，所以**一個行程**服務
整個節點：

```bash
python manage.py simulate_device     --device ZQS-BESS-0001=battery     --device ZQS-METER-0001=meter     --device ZQS-PV-0001=pv \
    --device ZQS-FC-0001=fuelcell --interval 5
```

`dev.ps1` / `dev.sh` 起的就是這一個行程（`zqs-sim-gateway`）。

> **不要為了每台設備各開一個行程。** Sparkplug 下一條連線就是一個 edge node，它
> 擁有一個 `seq` 計數器與一組生死序號。三個行程都自稱 `ZQS-GW-0001` 的話，序號會
> 各自遞增卻共用一個編號空間，而且 MQTT 會讓後連上的把先連上的踢掉——症狀是無限
> 互踢加上永遠對不上的序號。要多個行程，就多開幾個 edge node。

模擬器發布的是與 [device-protocol.md](device-protocol.md) 完全相同的 Sparkplug
訊息——包含 NDEATH 遺言、NBIRTH、帶別名的 DBIRTH、回應命令與重生要求——因此可以
直接當作設備端實作的參考。需要 broker；資料要進到資料庫還需要 ingestor 與 worker。

---

## 4. 手動逐步執行

```bash
python -m venv .venv
.venv\Scripts\activate                     # PowerShell
pip install -r requirements.txt
copy .env.example .env

python manage.py migrate
python manage.py bootstrap                 # built-in metrics + blueprints
python manage.py seed_demo                 # tenant, site, devices, rules, tariff
python manage.py generate_history --days 3 --with-faults

python manage.py runserver                 # terminal 1
cd frontend && npm install && npm run dev  # terminal 2
```

需要即時資料路徑時再加上：

```bash
python manage.py run_broker                # terminal 3，內建開發用 broker
python manage.py run_pipeline              # terminal 4，ingestor + worker
```

要跑正式環境的形狀（真 EMQX + Redis）就換成兩個獨立行程：

```bash
python manage.py run_ingestor              # terminal 3
python manage.py run_worker                # terminal 4
```

手動跑時記得環境變數要對上：內建 broker 需要
`MQTT_PROTOCOL_VERSION=311`、`MQTT_USE_SHARED_SUBSCRIPTION=0`、
`BUS_BACKEND=memory`。啟動腳本會幫你設好，手動跑不會。

### 週期性工作

```bash
python manage.py run_scheduler             # terminal 5，一個行程包辦全部
```

它每 5 分鐘依序做四件事：

| 工作 | 做什麼 |
| --- | --- |
| `aggregate_energy` | 功率樣本 → 15 分鐘能源區間 + 成本分項 |
| `build_rollups` | 圖表用的聚合桶 |
| `rebuild_sessions` | 充電／放電／運轉 session 的回算 |
| `run_dispatch` | 把生效中的調度時段變成實際命令 |

順序是刻意的：調度引擎會讀即時 SOC 決定方案允不允許放電，而前面三步剛好把它要讀的
東西刷新了。

> **`run_dispatch` 會對實體硬體送出真正的命令。** 本機只想要聚合與 session 回算
> 時，用 `python manage.py run_scheduler --no-dispatch` 把它關掉。
>
> 想先看它「會下什麼」而不真的下，用
> `python manage.py run_dispatch --dry-run`，或在 console 的儲能頁看調度預覽。

各項也可以單獨跑一次：

```bash
python manage.py aggregate_energy --hours 2
python manage.py rebuild_sessions --hours 2
python manage.py run_dispatch --dry-run
```

---

## 5. 疑難排解

**8000 或 5173 連接埠已被占用。** 前一組服務還在跑。執行
`.\scripts\stop.ps1`，或在 `dev.sh` 的終端機按 Ctrl-C。

**剛裝完 Node 卻找不到 `npm`。** PATH 只有新開的 shell 才會讀到。開一個新的
終端機；啟動腳本本身也會去 `C:\Program Files\nodejs` 找。

**Console 載入了但每個請求都失敗。** API 沒在跑，或是換到別的連接埠。檢查
<http://127.0.0.1:8000/healthz>；若你改過位置，也檢查 `VITE_PROXY_TARGET`。

**系統健康裡的 MQTT 顯示「未使用」。** 你是用 `-NoBroker` 啟動的，或是 `.env` 裡設了
`MQTT_ENABLED=0`。這不是故障，所以它不計入整體判定。拿掉那個旗標重新啟動即可。

**MQTT 顯示紅色的連線錯誤。** 這代表 `MQTT_ENABLED=1` 但真的連不上。通常是自己手動
跑 `manage.py runserver` 而沒有經過啟動腳本——那樣就沒有人幫你起 broker。另外開一個
終端機跑 `python manage.py run_broker`，或直接用啟動腳本。

**儲能頁面顯示資料已過期。** 即時電力流在五分鐘沒有樣本後就會被標記為過期。
只有回補資料時本來就會這樣——跑模擬器，或者就看圖表，反正圖表本來就是歷史
資料。

**過一陣子全部顯示離線。** 裝置靜默超過 `DEVICE_OFFLINE_GRACE_SECONDS`
（180 s）後，worker 就會把它標記為離線。預設模式有模擬器在跑，所以那三台會維持
上線；沒有模擬器對應的設備仍然會離線，這是正確的：回補的是歷史，不是即時連線。

**裝置離線且沒有資料進來。** 看 `zqs-pipeline`（或 `-Full` 時的 `zqs-ingestor`）
視窗。未註冊的 device id 依設計會被丟棄——先註冊裝置，或在 `.env` 設定
`INGEST_AUTO_PROVISION=1`。

若 `zqs-pipeline` 視窗顯示 `MQTT connect refused`，八成是協定版本對不上：內建
broker 只講 3.1.1，而 `.env` 裡的 `MQTT_PROTOCOL_VERSION` 被改成了 5。

**Alert 頁面是空的。** 產生的資料很乾淨時，不會有任何規則被違反，這是誠實的
結果。用 `--with-faults` 注入異常。

**運轉紀錄是空的。** session 判定預設是關的。到儲能頁的資產設定把該資產的
`session_tracking_enabled` 打開，再跑
`python manage.py rebuild_sessions --hours 720` 回算歷史。

**成本分項只有市電那一列。** 電池與發電機要在 `EnergyAsset` 上填 `cost_model` 與
`cost_parameters` 才會計價，然後重算區間
（`POST /api/ems/sites/{id}/rebuild-intervals`）。示範資料只有電池填了循環成本。

**調度預覽每個場域都寫「沒有生效的調度時段」。** 種子資料沒有建立
`DispatchWindow`。先建一個涵蓋現在的時段，引擎才有事可做。

**設備換了場域，儲能頁卻說新場域「尚未綁定能源資產」。** 這在 2026-08 之前確實會
發生；現在能源資產綁定會跟著設備一起搬。若是舊資料留下的狀態，到儲能頁把該資產重新
綁一次即可。

**設備清單、總覽檢視、即時數值的版面跟預期不同。** 這三個都是**每位使用者**的設定，
存在帳號上。換一個帳號登入會看到那個帳號自己的版面；即時數值的挑選對話框裡有「恢復
預設」。

**重來一次。** 刪掉 `data/zqs_cloud.sqlite3` 再跑一次 setup。本機沒有其他地方
留著狀態。

## 桌面模擬器主控台

`scripts\sim-console.ps1` 開啟圖形化的 Sparkplug 模擬器:一支程式就是一個完整
邊緣節點(gateway)加上其下所有模擬設備。可執行上線/離線、單發或自動遙測、
事件與告警注入,以及命令的按鍵測試——關閉自動回覆後,收到的 DCMD 會列在表格
中,由測試者手動按「接受/成功/失敗」觀察平台端的命令生命週期。
