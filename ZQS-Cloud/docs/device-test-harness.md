# 設備連線測試工具（MQTT 驗收 harness）

給要寫**設備端**（LabVIEW、韌體、任何 MQTT client）的人。

這份文件說明怎麼在**還沒有正式 broker**的情況下，確認你的設備真的能接上平台。

**趕時間的話只要記這一行：**

```powershell
.\scripts\test-device.ps1
```

---

## 0. 為什麼需要這個東西

設備端開發最痛的地方是回饋迴圈太長：接上 EMQX，連線被拒，日誌只寫
`bad_username_or_password`——但真正的原因可能是憑證錯、client id 被釘選、
topic 沒權限、或 payload 少一個欄位。你只能猜。

這個工具把猜測換成一份清單。它會：

1. 接受設備的 MQTT 連線，
2. 用**與正式環境完全相同的程式**檢查每一項，
3. 每收到一則訊息就即時印出通過／拒絕與原因，
4. 結束時印出一份驗收報告，明確回答一句話：**「這台設備可以接正式環境了嗎？」**

### 0.1 第一原則：測試環境只能更嚴，不能更鬆

這個工具的所有判斷都不是重寫的，是**呼叫正式環境的函式**：

| 檢查項目 | 呼叫的正式程式 |
| --- | --- |
| 帳號密碼 | `apps.devices.services.authenticate_device()` |
| Topic 權限 | `apps.devices.emqx` 的 `_PUBLISHABLE` / `_SUBSCRIBABLE` / `_split_topic()` |
| Payload 格式 | `services.ingestor.protocol.decode()` + `validate()` |
| Topic 結構 | `services.mqtt.topics` |

為什麼要這樣做：如果測試工具自己抄一份「合法 payload 長什麼樣」，任何一邊改了
之後兩份就會分岔，那時候「測試通過」等於沒有意義——你會拿著一張通過的報告，
接上正式環境然後失敗。

**有四項本工具比正式環境更嚴格**，這是刻意的，見 [§7](#7-比正式環境更嚴格的四項)。

---

## 1. 最短的用法

一行指令，什麼都不用先開：

```powershell
.\scripts\test-device.ps1
```

它會依序做兩件事：

1. **自我驗證**——確認這個測試工具本身是對的
2. **等你的設備連進來**——顯示流量，結束時給一份驗收報告

不需要先 `activate` 虛擬環境，不需要開兩個終端機，不需要記參數。啟動器會自己
用專案的 `.venv`。

跨平台或不想用 PowerShell 的話，直接跑 Python 也一樣：

```bash
python scripts/run_device_test.py self-test
python scripts/run_device_test.py device --device ZQS-BESS-0001
```

---

## 2. 為什麼一定要先自我驗證

⚠️ **不要跳過自我驗證直接測 LabVIEW。**

當 LabVIEW 沒通過某一項時，有兩個可能：設備錯了，或工具錯了。沒有對照組你分
不出來。

自我驗證會跑七個情境：

```
正常的參考設備          → 必須「全部通過」
故意用錯 client id      → 必須「剛好」抓到 Client ID 那一項
故意不宣告遺言          → 必須「剛好」抓到 LWT 那幾項
故意 clean_session=true → 必須「剛好」抓到 Clean session
故意 telemetry 少 ts    → 必須「剛好」抓到 Payload schema
故意用 QoS 0            → 必須「剛好」抓到 上行 QoS
故意收到命令不回 ack    → 命令回覆必須維持「未測」，不能謊稱通過
```

注意「剛好」兩個字。工具**漏報**會讓壞掉的設備矇混過關；工具**多報**會讓你去
追不存在的問題。兩種都算自我驗證失敗。

一個永遠只說「通過」的測試工具，比沒有測試工具還糟糕——它把「不知道」變成了
「假的安心」。

### 2.1 自我驗證要準備什麼？

**什麼都不用。** 它會自動建立一台名為 `ZQS-SELFTEST-xxxxxxxx` 的暫時設備、發
一組憑證、跑完之後把它刪掉（中途 Ctrl+C 也會刪）。你不必先註冊設備，也不必知
道任何密碼。

想改用既有設備的憑證測也可以：

```bash
python scripts/run_device_test.py self-test --device ZQS-BESS-0001
```

只跑其中一個情境（debug 用）：

```bash
python scripts/run_device_test.py self-test --only no_lwt
```

### 2.2 輸出長這樣

```
==========================================================================
  測試工具自我驗證
==========================================================================

先確認這個工具本身是對的，再拿它去測 LabVIEW。
每個情境都會跑一次參考設備：正常的那次必須全過，故意壞掉的
那幾次必須「剛好」被抓到對應的那一項——不多報，也不漏報。

  已建立暫時性測試設備 ZQS-SELFTEST-3AAD24A6（結束時自動刪除）

→ 正常設備（應該全部通過） …
   ✓ 全部通過（收到 10 則訊息）

→ Client ID 用 LabVIEW_1 …
   ✓ 如預期抓到 1 項（收到 6 則訊息）

→ 不宣告遺言（LWT） …
   ✓ 如預期抓到 5 項（收到 6 則訊息）

  … 略 …

--------------------------------------------------------------------------
7 / 7 個情境符合預期

結論：測試工具運作正常。
```

如果有情境不符預期，會直接標出是漏報還是多報：

```
[異常] 不宣告遺言（LWT）
        預期失敗項：lwt_declared、lwt_payload、lwt_qos、lwt_retain、lwt_topic
        實際失敗項：（無）
        → 工具沒有抓到應該失敗的項目：LWT 已宣告、…。
          這代表測試工具會放行有問題的設備。
```

這種情況下**不要**用它的報告判斷設備。

---

## 3. 測試真實設備（LabVIEW）

### 3.1 先註冊設備並拿到憑證

工具驗的是**真的憑證**，所以設備必須先存在於資料庫裡。到 console 新增設備，或
用 shell：

```bash
python manage.py shell
```

```python
from apps.devices.models import Device, DeviceCredential

device = Device.objects.get(device_id="ZQS-BESS-0001")
credential, password = DeviceCredential.issue(device)
print(credential.mqtt_username)  # dev-<組織代碼>-ZQS-BESS-0001
print(password)                  # 只會顯示這一次，請記下來
```

密碼是雜湊儲存的，**只在產生當下顯示一次**。弄丟了就重新 `issue()` 一次（舊
密碼會失效）。

設備的 `commissioning_state` 必須允許連線，且 `is_enabled` 為真，否則
`authenticate_device()` 會拒絕——這與正式環境行為一致，不是工具的限制。

> 啟動器**不會**把密碼寫進任何檔案。device 模式根本不需要密碼（是設備自己
> 帶上來的）；只有在你用 `self-test --device` 指定既有設備時才需要，這時可以
> 用 `--password`、環境變數 `ZQS_DEVICE_PASSWORD`，或什麼都不給讓它跳出不回
> 顯的輸入提示。

### 3.2 啟動

```powershell
.\scripts\test-device.ps1 -Device -DeviceId ZQS-BESS-0001
```

或：

```bash
python scripts/run_device_test.py device --device ZQS-BESS-0001
```

然後啟動 LabVIEW，連到這台電腦的 `1883` 埠。畫面會即時顯示：

```
·· TCP 連線建立 192.168.1.44:53214
>> CONNECT ZQS-BESS-0001 → 接受
>> SUBSCRIBE energy/devices/ZQS-BESS-0001/control  QoS 1
<< 14:22:07  energy/devices/ZQS-BESS-0001/status  [QoS 1  retained]
       {"status":"online","ts":1755678127000,"reason":"boot",...}
<< 14:22:08  energy/devices/ZQS-BESS-0001/telemetry  [QoS 1]
       {"ts":1755678128000,"metrics":{"battery_soc":62.0,...}}
```

被拒絕的訊息會即時說明原因，不必等到最後：

```
<< 14:22:09  energy/devices/ZQS-BESS-0001/telemetry  [QoS 0]
       {"metrics":{"battery_soc":62.0}}
       拒絕：[schema_invalid] telemetry 缺少必要欄位 ts
```

### 3.3 什麼時候會結束

| 條件 | 怎麼設定 |
| --- | --- |
| 你按 Ctrl+C | 隨時 |
| 等不到設備連進來 | `--timeout`（預設 300 秒） |
| 設備連上後測夠久了 | `--duration 60` |
| 收到足夠的訊息 | `--max-messages 50` |

結束時印出完整驗收報告，並自動寫一份到 `logs/`：

```
報告已寫入 D:\Working Space\Python\ZQS-Cloud\logs\device-test-device-ZQS-BESS-0001-20260820-142207.txt
```

檔名含時間戳，不會互相覆蓋。報告是 UTF-8（含 BOM），用記事本或 Excel 打開都
不會變亂碼，可以直接貼進工單。不想留檔就加 `--no-report`。

---

## 4. 下發命令

### 4.1 自動下發一次

```powershell
.\scripts\test-device.ps1 -Device -DeviceId ZQS-BESS-0001 `
    -Command set_power_limit -Params '{"limit_w": 400000}'
```

工具會在設備訂閱之後（預設等 8 秒，可用 `--command-delay` 調整）下發一則命令，
然後檢查 `control/ack`：

```
>> 下發命令 set_power_limit  command_id=bd167ce4-8230-40e8-8f85-358ef681a262
<< 14:22:15  energy/devices/ZQS-BESS-0001/control/ack  [QoS 1]
       {"command_id":"bd167ce4-...","status":"succeeded","ts":...}
```

設備必須把 `command_id` **原樣**帶回。平台靠它把回覆對回請求；改動或省略的話，
命令在平台側會一直停在「等待中」直到逾時。

PowerShell 的單引號字串會原樣傳遞，所以 `-Params '{"limit_w": 400000}'` 可以
直接用。cmd.exe 需要跳脫：`--params "{\"limit_w\": 400000}"`。

### 4.2 互動下發

想一邊看反應一邊試不同命令：

```bash
python scripts/run_device_test.py device --device ZQS-BESS-0001 --interactive
```

然後直接打字：

```
set_power_limit {"limit_w": 400000}
reboot
q
```

格式是 `命令名稱 <JSON 參數>`，參數可省略。輸入 `q` 結束並印出報告。

---

## 5. 結束碼

啟動器會回傳有意義的結束碼，方便串批次檔或 CI：

| 碼 | 意思 | 典型情況 |
| --- | --- | --- |
| `0` | 通過 | 設備全部必要項通過；或自我驗證七個情境都符合預期 |
| `1` | **驗收失敗** | 設備有必要項不合格；或自我驗證發現工具漏報／多報 |
| `2` | **無法執行** | 埠被占用、參數錯誤、找不到憑證、沒有 `.venv` |
| `3` | **測試未完成** | 逾時都沒有設備連進來，或必要行為從未發生 |
| `130` | 使用者中斷 | 自我驗證途中按了 Ctrl+C |

`1` 和 `2`、`3` 是刻意分開的：CI 需要區分「設備壞了」與「測試根本沒跑起來」，
把兩者混成同一個非零碼會讓自動化把環境問題誤判成品質問題。

批次檔範例：

```batch
python scripts\run_device_test.py self-test --no-report
if errorlevel 2 (
    echo 測試環境有問題，不是設備的錯
    exit /b 2
)
if errorlevel 1 (
    echo 測試工具自我驗證失敗
    exit /b 1
)
echo 工具正常
```

---

## 6. 手動模式（進階）

啟動器底下是兩個 management command，需要細部控制時可以直接用。這是**兩個終端
機**的舊流程：

```bash
# 終端機 A
python manage.py run_test_broker --port 1883

# 終端機 B
python manage.py run_reference_device --device ZQS-BESS-0001 \
    --password <密碼> --duration 30 --abrupt-exit
```

`--abrupt-exit` 會在結束時**不送 DISCONNECT 直接斷開 socket**，這是唯一能讓
broker 真的送出遺言（LWT）的方式——正常斷線依 MQTT 規範會丟棄遺言，這是協定
行為，不是工具的怪癖。

`--misbehave` 讓模擬器故意違反一條規則：

| `--misbehave` | 模擬器做了什麼 | 報告應該失敗的項目 |
| --- | --- | --- |
| `bad_client_id` | 用 `LabVIEW_1` 當 client id | Client ID 格式 |
| `no_lwt` | 不宣告遺言 | LWT 已宣告（連帶 topic/QoS/retain/payload） |
| `clean_session` | `clean_session=true` | Clean session |
| `bad_payload` | telemetry 少了 `ts` | Payload 通過正式 schema |
| `bad_qos` | telemetry 用 QoS 0 | 上行 QoS |
| `no_ack` | 收到命令不回覆 | 命令回覆（維持「未測」） |

`self-test` 模式就是把這張表自動跑一遍並比對結果，所以平常不需要手動操作。

---

## 7. 比正式環境更嚴格的四項

刻意的。更嚴格是安全的；更寬鬆會變成謊言。這四項在報告裡都會標注
「（本工具在這一項比正式環境嚴格，見文件說明）」。

| 項目 | 正式環境 | 本工具 | 為什麼 |
| --- | --- | --- | --- |
| **Client ID 格式** | 只有在 `DeviceCredential.allowed_client_id` 有設值時才釘選，而它**預設是空的** | 一律要求 `zqs:<device_id>` | 營運人員哪天打開釘選，格式不對的設備會立刻全部斷線。現在改比那時候改便宜。 |
| **Clean session** | broker 照收 `true` | 要求 `false` | `true` 會讓 broker 在斷線時丟掉未送達的 QoS 1 下行命令，設備重連後收不到。這種錯不會有錯誤訊息，只會「命令偶爾沒生效」。 |
| **status 設 retained** | broker 不在乎 | 要求 `retain=true` | 沒有 retained，後連上的 console 看不到設備目前狀態，畫面會空白。 |
| **Keepalive 範圍** | 任何值都合法 | 建議 45 秒，超出 1–120 只給「注意」 | 太大會讓離線判定拖到數分鐘。這一項只警告，不擋。 |

其中 client id 那一項最值得注意：**正式環境現在會放行、以後可能不放行**。

---

## 8. 完整驗收清單

工具檢查 22 項，順序照設備實際執行的流程。「必要」項全部通過才會判定可以上線。

### 8.1 CONNECT 階段

| # | 項目 | 要求 | 必要 |
| --- | --- | --- | --- |
| 1 | MQTT 協定版本 | 3.1.1（level 4）或 5.0（level 5） | ✔ |
| 2 | Client ID 格式 | `zqs:<device_id>` | ✔ |
| 3 | Username 格式 | `dev-<組織代碼>-<device_id>` | ✔ |
| 4 | 帳號密碼驗證 | 通過 `authenticate_device()` | ✔ |
| 5 | Keepalive | 1–120 秒，建議 45 | — |
| 6 | Clean session | `false` | ✔ |
| 7 | LWT 已宣告 | CONNECT 帶 will flag | ✔ |
| 8 | LWT topic | `energy/devices/<device_id>/status` | ✔ |
| 9 | LWT QoS | `1` | ✔ |
| 10 | LWT retained | `true` | ✔ |
| 11 | LWT payload | JSON 物件，`status="offline"` | ✔ |

**遺言必須在 CONNECT 封包裡宣告**，連上之後再設是沒有用的——broker 只在
CONNECT 那一刻知道你的遺言是什麼。

### 8.2 SUBSCRIBE 階段

| # | 項目 | 要求 | 必要 |
| --- | --- | --- | --- |
| 12 | 訂閱 control topic | `energy/devices/<device_id>/control` | ✔ |
| 13 | 訂閱權限（ACL） | 只能訂閱自己的 `control` | ✔ |
| 14 | 訂閱 QoS | `1` | — |

**先訂閱再發上線訊息**。反過來的話，平台看到設備上線就下發命令，而設備還沒
訂閱好，那則命令就掉了。

### 8.3 PUBLISH 階段

| # | 項目 | 要求 | 必要 |
| --- | --- | --- | --- |
| 15 | 上線後發布 status | 連線後立即發一則 `status="online"` | ✔ |
| 16 | status 設為 retained | `retain=true` | ✔ |
| 17 | 發布權限（ACL） | 只發布到自己的 topic 子樹 | ✔ |
| 18 | 上行 QoS | `1` | ✔ |
| 19 | Payload 通過正式 schema | 與 ingestor 相同的 `decode()` + `validate()` | ✔ |
| 20 | 收到 telemetry | 至少一則 | ✔ |

可發布的 topic 後綴：`telemetry`、`status`、`event`、`alarm`、`control/ack`。
可訂閱的只有 `control`。

發布到自己的 `control`（而不是 `control/ack`）會被拒絕——那是平台下行用的。

### 8.4 互動

| # | 項目 | 要求 | 必要 |
| --- | --- | --- | --- |
| 21 | 命令回覆（control/ack） | 收到命令後回 ack，`command_id` 原樣帶回 | — |
| 22 | LWT 實測 | 強制斷線後 broker 確實送出遺言 | — |

這兩項是選用的，因為要觀察到它們必須主動觸發（下發命令／強制斷線）。**但正式
環境會依賴它們**，所以強烈建議測。

---

## 9. 全部參數

### `scripts\test-device.ps1`（PowerShell 包裝）

| 參數 | 說明 |
| --- | --- |
| （無） | 自我驗證 → 再等設備。預設流程 |
| `-SelfTest` | 只做自我驗證 |
| `-Device` | 只測設備，跳過自我驗證 |
| `-DeviceId <id>` | 預期連進來的 `device_id`（下發命令時需要） |
| `-Port <n>` | 監聽埠，預設 1883 |
| `-Timeout <秒>` | 等待設備連線的秒數，預設 300 |
| `-Duration <秒>` | 設備連上後再測幾秒。0 表示等 Ctrl+C |
| `-Command <名稱>` | 設備訂閱後自動下發的命令 |
| `-Params '<JSON>'` | 命令參數 |
| `-Interactive` | 從鍵盤逐一下發命令 |
| `-NoReport` | 不寫報告檔 |

自我驗證沒過時，包裝腳本**不會**繼續往下測設備——這時候的報告不能當依據。

### `scripts\run_device_test.py self-test`

| 參數 | 預設 | 說明 |
| --- | --- | --- |
| `--only <情境>` | — | 只跑一個情境，例如 `--only no_lwt` |
| `--device` | — | 用既有設備憑證。省略則自動建立暫時設備並刪除 |
| `--username` / `--password` | — | 搭配 `--device` |
| `--no-report` | 關 | 不寫報告檔 |

### `scripts\run_device_test.py device`

| 參數 | 預設 | 說明 |
| --- | --- | --- |
| `--host` | `0.0.0.0` | 綁定位址。要讓別台機器連進來就維持 `0.0.0.0` |
| `--port` | `1883` | 監聽埠 |
| `--device` | — | 預期的 `device_id` |
| `--timeout` | `300` | 等待設備連線的秒數 |
| `--duration` | `0` | 設備連上後再測幾秒。`0` 表示等 Ctrl+C |
| `--max-messages` | `0` | 收到幾則訊息就結束。`0` 表示不限 |
| `--command` / `--params` | — | 自動下發的命令與參數 |
| `--command-delay` | `8.0` | 幾秒後下發命令 |
| `--interactive` | 關 | 從鍵盤逐一下發命令 |
| `--no-color` | 關 | 關閉彩色輸出 |
| `--no-report` | 關 | 不寫報告檔 |

### `run_test_broker`（底層 management command）

| 參數 | 預設 | 說明 |
| --- | --- | --- |
| `--host` | `0.0.0.0` | 綁定位址。要讓別台機器連進來就維持 `0.0.0.0` |
| `--port` | `1883` | 監聽埠 |
| `--command` | — | 設備訂閱後下發這個命令 |
| `--params` | `{}` | 命令參數（JSON） |
| `--command-delay` | `8.0` | 幾秒後下發命令 |
| `--duration` | `0` | 幾秒後自動停止。`0` 表示跑到 Ctrl-C |
| `--report-file` | — | 同時把報告寫到檔案（可貼進工單） |

### `run_reference_device`

| 參數 | 預設 | 說明 |
| --- | --- | --- |
| `--device` | 必填 | `device_id` |
| `--username` | 自動查 | MQTT username |
| `--password` | 必填 | MQTT 密碼 |
| `--host` / `--port` | `127.0.0.1` / `1883` | 測試工具的位址 |
| `--interval` | `5.0` | telemetry 間隔（秒） |
| `--keepalive` | `45` | keepalive |
| `--duration` | `0` | 幾秒後停止 |
| `--abrupt-exit` | 關 | 不送 DISCONNECT 直接斷線，用來觸發遺言 |
| `--misbehave` | — | 故意違反一條規則，見 [§6](#6-手動模式進階) |

---

## 10. 從別台機器連進來（LabVIEW 在另一台電腦）

1. 查本機 IP：`ipconfig`（找 IPv4 位址，例如 `192.168.1.23`）
2. 工具用 `--host 0.0.0.0` 啟動（預設就是）
3. Windows 防火牆放行該埠：

```powershell
# 需要系統管理員權限
New-NetFirewallRule -DisplayName "ZQS test broker" -Direction Inbound `
    -Protocol TCP -LocalPort 1883 -Action Allow -Profile Private
```

4. LabVIEW 連 `192.168.1.23:1883`

⚠️ 這條規則只在 **Private** 網路設定檔生效。如果 Wi-Fi 被 Windows 歸類成
Public，連線會被擋；請到「設定 → 網路和網際網路」把該網路改成私人網路。

⚠️ **這個工具沒有 TLS，密碼是明文傳輸的。** 只在開發用的區域網路裡跑，不要
放到公開網路上。

---

## 11. 這個工具**證明不了**什麼

誠實比方便重要。以下三項本工具無法驗證，通過報告之後**仍然建議對真正的 EMQX
做一次煙霧測試**：

| 無法驗證 | 為什麼 | 風險 |
| --- | --- | --- |
| **retained 訊息重播** | 工具記錄 retain flag，但不會在後續訂閱時重播 | 設備的 retained status 在真實 broker 上會不會正確重播、會不會被舊值覆蓋 |
| **session 跨重連保存** | `clean_session=false` 的 session 狀態不會保留 | 斷線期間累積的 QoS 1 命令能否在重連後補送 |
| **TLS** | 工具只講明文 TCP | 正式環境用 8883 + TLS，憑證驗證、SNI、握手都可能出問題 |

另外工具只處理**單一設備連線**（`only_session()`），不驗證 shared subscription
或多設備併發。

### 11.1 為什麼不直接跑一個真的 broker

考慮過三條路：

1. **自己寫一個完整 broker** — 會在 retained 重播、session 保存、shared
   subscription 上與 EMQX 分岔，產生**假的通過**。假的通過比沒有測試更危險。
2. **用 amqtt 之類的 Python broker** — 能跑 MQTT，但它不知道平台的規則，還是
   要另外寫一層檢查，而且失敗訊息會是 broker 的措辭而不是給設備開發者看的。
3. **本工具的做法** — 只講「足以觀察一切」的 MQTT，所有判斷都呼叫正式環境的
   程式，並且**明確列出自己證明不了的東西**。

選 3。它不假裝是 broker，它是一份會自己執行的驗收清單。

真正的 EMQX 需要 Docker 或 WSL2；等環境備好之後，用它做最後一關的煙霧測試。

---

## 12. 常見失敗與原因

| 報告顯示 | 實際原因 |
| --- | --- |
| 帳號密碼驗證失敗 | 密碼打錯、設備已停用或退役、或憑證被輪替過 |
| Client ID 格式失敗 | LabVIEW 預設用自己的 client id，要手動改成 `zqs:<device_id>` |
| LWT 已宣告失敗 | 連線後才設遺言。必須在 CONNECT 之前設定 |
| Payload 通過正式 schema 失敗 | 通常是缺 `ts`，或 `ts` 用了秒而不是毫秒 |
| 上行 QoS 失敗 | LabVIEW toolkit 的 publish 預設常是 QoS 0 |
| 發布權限失敗 | 發到別台設備的 topic，或發到自己的 `control` 而非 `control/ack` |
| 命令回覆維持「未測」 | 沒下發命令（加 `--command`），或設備沒回 ack |
| LWT 實測維持「注意」 | 用了正常斷線。這是 MQTT 規範行為——要實測請直接拔網路線或關電源 |
| 結束碼 2、沒有任何輸出 | 埠被占用，或找不到 `.venv`。訊息會直接說明處理方式 |

---

## 13. 相關文件

- [device-protocol.md](device-protocol.md) — 完整的 topic 與 payload schema 契約
- [system-logic.md](system-logic.md) — 平台的行為規則：命令什麼時候被擋、哪些情況記 null
- [codebase-guide.md](codebase-guide.md) — 程式碼結構
- [labview-integration.md](labview-integration.md) — LabVIEW 透過 Python Node 啟停服務
