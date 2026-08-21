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
telemetry，然後啟動 API 與 console 並開啟瀏覽器。

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
| `-Full` / `--full` | 另外啟動 ingestor 與 worker（需要 Redis + EMQX） |
| `-Simulate` / `--simulate` | 同 `-Full`，再加上模擬裝置透過 MQTT 發布資料 |
| `-HistoryDays` / `--history-days` | setup 時回補的天數（預設 3） |
| `-NoBrowser` | 不要開啟瀏覽器 |

### 啟動後有什麼

| | |
| --- | --- |
| Console | <http://127.0.0.1:5173> |
| API docs | <http://127.0.0.1:8000/api/docs> |
| EMQX dashboard（`-Full`） | <http://127.0.0.1:18083> — admin / public |

以 `admin@example.com` / `ChangeMe-2026!` 登入。`operator@example.com` 與
`viewer@example.com` 使用相同密碼，適合用來看 UI 如何隨角色改變：operator 可以
下命令但不能註冊裝置；viewer 兩者都不行。

---

## 2. 三種模式，以及為什麼是三種

**預設 — API + console。** 沒有 broker、沒有 queue。API 直接讀寫 SQLite，所以
每一頁都能用：裝置註冊表、歷史圖表、儲能儀表板、alert、設定。*沒有*在跑的是
即時擷取，因此你看著畫面時不會有新資料進來。

開發 UI 或摸索資料模型時，就用這個模式。

**`-Full` — 再加上 ingestor 與 worker。** 這會走完整條真實資料路徑：
MQTT → ingestor → queue → worker → 資料庫。需要 Redis 與 EMQX：

```bash
docker run -d --name redis -p 6379:6379 redis:7-alpine
docker run -d --name emqx -p 1883:1883 -p 18083:18083 emqx/emqx:5.8
```

這裡的 Redis 不是選配。ingestor 與 worker 是兩個獨立行程，而
`BUS_BACKEND=memory` 是行程內的 queue——它們看不到彼此的訊息。啟動腳本在此
模式下會自動切換成 `BUS_BACKEND=redis`，且只要缺少其中一項服務就拒絕啟動。

**`-Simulate` — 再加上模擬硬體。** 三個模擬器在真實的 topic 上發布電池、電表
與 PV 的 telemetry，畫面上的數值會跳動，整條鏈路也都有負載。這是沒有硬體時
最接近硬體的做法。

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

```bash
python manage.py simulate_device --device ZQS-BESS-0001 --profile battery --interval 5
python manage.py simulate_device --device ZQS-METER-0001 --profile meter  --interval 5
python manage.py simulate_device --device ZQS-PV-0001    --profile pv     --interval 10
```

以 [device-protocol.md](device-protocol.md) 中完全相同的 payload 透過 MQTT
發布，因此也可以當作 LabVIEW 實作的參考。需要 broker；資料要進到資料庫還
需要 ingestor 與 worker。

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
python manage.py run_ingestor              # terminal 3
python manage.py run_worker                # terminal 4
```

---

## 5. 疑難排解

**8000 或 5173 連接埠已被占用。** 前一組服務還在跑。執行
`.\scripts\stop.ps1`，或在 `dev.sh` 的終端機按 Ctrl-C。

**剛裝完 Node 卻找不到 `npm`。** PATH 只有新開的 shell 才會讀到。開一個新的
終端機；啟動腳本本身也會去 `C:\Program Files\nodejs` 找。

**Console 載入了但每個請求都失敗。** API 沒在跑，或是換到別的連接埠。檢查
<http://127.0.0.1:8000/healthz>；若你改過位置，也檢查 `VITE_PROXY_TARGET`。

**儲能頁面顯示資料已過期。** 即時電力流在五分鐘沒有樣本後就會被標記為過期。
只有回補資料時本來就會這樣——跑模擬器，或者就看圖表，反正圖表本來就是歷史
資料。

**過一陣子全部顯示離線。** 裝置靜默超過 `DEVICE_OFFLINE_GRACE_SECONDS`
（180 s）後，worker 就會把它標記為離線。這是正確的：回補的是歷史，不是即時
連線。

**`-Full` 模式下裝置離線且沒有資料進來。** 看 `zqs-ingestor` 視窗。未註冊的
device id 依設計會被丟棄——先註冊裝置，或在 `.env` 設定
`INGEST_AUTO_PROVISION=1`。

**Alert 頁面是空的。** 產生的資料很乾淨時，不會有任何規則被違反，這是誠實的
結果。用 `--with-faults` 注入異常。

**重來一次。** 刪掉 `data/zqs_cloud.sqlite3` 再跑一次 setup。本機沒有其他地方
留著狀態。
