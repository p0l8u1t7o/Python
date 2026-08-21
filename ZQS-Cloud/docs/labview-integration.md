# 從 LabVIEW 控制服務

[`services/labview/labview_api.py`](../services/labview/labview_api.py) 讓
LabVIEW VI 透過 Python Node 啟動與停止 ZQS Cloud 的各項服務。

Python Node 是同步呼叫：block diagram 會等函式回傳，而且無法中斷它。因此這裡
的每個函式都在毫秒內回傳，並透過可輪詢的狀態回報進度，絕不阻塞。

---

## 第一次呼叫之前

這個模組只負責監管行程，本身不執行 Django。請先把專案設定好，才有東西可以
啟動：

```powershell
.\scripts\dev.ps1 -Setup -NoBrowser
.\scripts\stop.ps1
```

這會建立 `.venv`、安裝相依套件、遷移資料庫並寫入種子資料。之後
`labview_api` 會用 `.venv\Scripts\python.exe` 啟動服務——與 `dev.ps1` 使用的
是同一個直譯器。

---

## LabVIEW 設定

| Python Node 上的欄位 | 值 |
| --- | --- |
| Python Version | 你的 LabVIEW 版本所支援的版本 |
| Module Path | `D:\Working Space\Python\ZQS-Cloud\services\labview\labview_api.py` |
| Function Name | 下列函式名稱之一 |

兩邊的直譯器不必相同。`labview_api` 只 import 標準函式庫——不需要 Django，也
不需要 `requirements.txt`——所以 LabVIEW 可以用它支援的 Python 載入這個模組，
底下的服務則跑在專案的 3.12 virtualenv 上。

請把 *session* 接線貫穿整個 VI。LabVIEW 會在多次呼叫之間保持該 Python session
存活，這正是模組能記住自己啟動的行程 handle 的原因。

---

## 函式

| 函式 | 參數 | 回傳 | 說明 |
| --- | --- | --- | --- |
| `start_server` | `services`（str） | int 回傳碼 | 啟動後立即回傳，不等待服務就緒 |
| `stop_server` | `services`（str）、`grace_seconds`（float） | int 回傳碼 | 送出訊號後立即回傳，寬限期在背景進行 |
| `get_status` | `service`（str） | int 狀態碼 | 要輪詢的就是這個 |
| `get_status_json` | — | str (JSON) | 每個服務的 pid、exit code、運行時間、log 路徑 |
| `get_last_error` | — | str | 正常時為 `""`；回傳負數碼後讀這個 |
| `clear_last_error` | — | int（恆為 0） | |
| `list_services` | — | str 陣列 | `api`、`ingestor`、`worker`、`scheduler` |
| `get_pid` | `service`（str） | int | 沒在跑時為 0 |
| `get_log_path` | `service`（str） | str | 絕對路徑，名稱錯誤時為 `""` |
| `get_root` | — | str | 專案根目錄，用來確認接對了 |

`services` 用 `""` 或 `"all"` 代表全部，也可以是逗號分隔的清單，例如
`"api,worker"`（用空白分隔也可以，大小寫不拘）。LabVIEW 的一維字串陣列同樣
接受。`grace_seconds` 會被夾在 0.5–120 s 之間，預設為 5。

型別僅限 Python Node 能表示的範圍：`int`、`float`、`str` 以及這些型別的陣列。
沒有任何函式會回傳 `None`、boolean、dictionary 或物件，也沒有任何函式會拋出
例外——失敗一律以負數回傳碼表示，訊息放在 `get_last_error`。

### 服務

| 名稱 | 命令 | 需要 |
| --- | --- | --- |
| `api` | `manage.py runserver --noreload 127.0.0.1:8000` | 無 |
| `ingestor` | `manage.py run_ingestor` | EMQX 1883、Redis 6379 |
| `worker` | `manage.py run_worker` | Redis 6379 |
| `scheduler` | `manage.py run_scheduler` | 無 |

`--noreload` 是刻意的：Django 的 autoreloader 會 fork 出第二個行程，對父行程
送訊號會留下子行程繼續占著 8000 埠。

啟動 `ingestor` 或 `worker` 時，若環境變數尚未指定 backend，會為子行程設定
`BUS_BACKEND=redis`——與 `dev.ps1` 同一套規則，因為不同行程無法共用
in-memory bus。

---

## 狀態碼 — `get_status`

| 代碼 | 意義 |
| --- | --- |
| `0` | STOPPED — 沒在跑：從未啟動，或已正常停止 |
| `1` | RUNNING — 行程存活中 |
| `2` | STOPPING — 已送出訊號；處於寬限期內或正在被強制結束 |
| `3` | EXITED — 自行以非零代碼結束；請看 log |
| `-1` | UNKNOWN — 未知的服務名稱 |

傳 `""` 時，答案涵蓋全部四個服務，依優先序判定：只要有任何一個在停止中就回
2，其次只要有任何一個非預期結束就回 3，再其次只要有任何一個在跑就回 1，否則
回 0。需要知道是*哪一個*時，用 `get_status_json`。

`1` 只代表行程存活，不代表 API 已經在回應。要判斷就緒，請在狀態變成 1 之後，
用 LabVIEW 的 HTTP client 輪詢 `http://127.0.0.1:8000/healthz`。

## 回傳碼 — `start_server`、`stop_server`

| 代碼 | 意義 |
| --- | --- |
| `0` | OK — 請求已受理 |
| `1` | ALREADY RUNNING — 要求的服務全都已在執行，沒有重啟任何一個 |
| `-1` | 內部錯誤 |
| `-2` | 未知的服務名稱 |
| `-3` | 找不到 Python 直譯器——執行 `dev.ps1 -Setup`，或設定 `ZQS_PYTHON` |
| `-4` | 產生行程失敗——路徑錯誤、權限不足，或無法寫入 log 檔 |
| `-5` | 正在停止中——等狀態變成 0 再重試 |

`0` 與 `1` 都算成功。任何負數都視為失敗，並讀取 `get_last_error`。

---

## 輪詢模式

### 啟動

```
start_server("")            →  code
  code < 0                  →  get_last_error, show it, stop
  code = 0 or 1             →  continue
loop, every 250-500 ms:
    get_status("")          →  1  ready to work
                            →  3  a service died   → get_status_json, log it
                            →  0  still nothing up → give up after ~30 s
```

延遲才「失敗」的啟動——設定錯誤、連接埠被占用、Redis 沒開——會表現為狀態 3，
並在 `get_status_json` 中帶有非零的 `exit_code`，通常一兩秒內就會出現。不要把
第一次讀到的 0 當成失敗，給它一段逾時時間。

### 停止

```
stop_server("", 5.0)        →  0
loop, every 250-500 ms:
    get_status("")          →  2  still shutting down, keep polling
                            →  0  done
```

這個迴圈保證會結束：寬限期一到，背景執行緒就會強制結束殘存的行程，因此不需要
LabVIEW 再做任何呼叫，狀態就會走到 0。判定為異常之前，請至少等
`grace_seconds + 5 s`。

### 重新啟動

沒有 `restart_server`。請呼叫 `stop_server`，輪詢到 0，再呼叫 `start_server`。
在關閉過程中啟動會回傳 `-5`，而不是與它競爭。

### 若 VI 中止

這些服務是獨立行程，會比 VI 活得久，而模組的狀態存在 LabVIEW 的 Python
session 裡。重新開啟 session 之後，你會拿到一個沒有任何 handle 的監管者：舊
行程還在跑，`get_status` 卻回報 0，接著 `start_server` 就會因為連接埠被占用而
失敗。用 `scripts\stop.ps1` 收拾，它是靠命令列比對找出這些行程的。

---

## Log

每個服務都以附加方式寫入 `logs\labview\<service>.log`，超過 5 MB 會輪替為
`.log.1`。`get_log_path` 會回傳路徑，讓 VI 可以顯示。

輸出導向檔案而不是 pipe 是刻意的：沒有人讀取的 OS pipe 大約 64 KB 就會塞滿，
子行程下一次寫入時便永遠卡住。這個模組不會去讀子行程的輸出，所以用 pipe 最終
會讓整組服務停擺。這一點有對應的回歸測試。

---

## 環境變數覆寫

| 變數 | 作用 |
| --- | --- |
| `ZQS_PYTHON` | 用來啟動服務的直譯器，取代 `.venv` |
| `ZQS_API_BIND` | API 綁定位址，預設 `127.0.0.1:8000` |
| `ZQS_LABVIEW_CONSOLE` | 設為 `1` 會讓每個服務有自己的可見 console 視窗 |
| `BUS_BACKEND` | 明確指定即可覆寫自動選用的 `redis` |

---

## Windows 的行為，以及一個必須誠實說明的限制

子行程以 `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` 建立，同時關閉 `stdin`
並把輸出導向 log 檔。新的 process group 代表某人在自己的 console 按下 Ctrl-C
不會波及 LabVIEW 所管理的服務，也讓 `CTRL_BREAK_EVENT` 能只送達單一服務。

限制在於：`CREATE_NO_WINDOW` 會讓子行程沒有 console，而沒有 console 的行程
無法*接收* console control event。因此 `stop_server` 送出的、比較禮貌的
`CTRL_BREAK_EVENT` 只是盡力而為——在預設旗標下它通常不會有任何作用，關閉是在
寬限期屆滿、行程被終止時才完成的。這種方式很粗暴：沒有 Django 的關閉掛鉤，
也沒有最後的 flush。

若優雅關閉比畫面整潔重要，請設定 `ZQS_LABVIEW_CONSOLE=1`。屆時每個服務會有
自己的 console 視窗，`CTRL_BREAK_EVENT` 送得到，`run_ingestor`、`run_worker`
與 `run_scheduler` 也會據此乾淨地結束——`run_scheduler` 就是為此明確處理了
`SIGBREAK`。強制結束仍保留為最後的保險。

在 Linux 與 macOS 上走的是對應的路徑：建立新的 session、對 process group 送
`SIGTERM`、寬限期過後送 `SIGKILL`。這條路徑有測試涵蓋；Windows 的旗標無法在
非 Windows 環境實測，因此 `tests/test_labview_api.py` 只斷言旗標是如何選出來
的，實際效果留待在 Windows 機器上確認。

---

## 測試

```bash
python manage.py test tests.test_labview_api
```

38 個測試，不需要資料庫，約一秒跑完。涵蓋狀態機、重複啟動、不阻塞的保證（對
一個跑 60 秒的子行程呼叫 stop，一秒內回傳）、子行程忽略 `SIGTERM` 時的寬限期
強制結束、當機與正常結束的區分回報、800 KB 輸出下的 log 導向，以及任何參數
——包括垃圾型別——都無法讓函式拋出例外。
