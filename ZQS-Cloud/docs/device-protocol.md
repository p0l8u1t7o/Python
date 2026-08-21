# ZQS Cloud 裝置通訊協定 (v1)

裝置端實作（LabVIEW 或其他）與平台通訊所需的一切。伺服器會驗證本文描述的
每一個欄位，不符合的一律拒絕，因此請把本文件視為契約。

---

## 1. 連線

| 項目 | 值 |
| --- | --- |
| Protocol | MQTT 3.1.1 或 5.0 |
| Broker | EMQX |
| Port | `1883` 未加密，`8883` TLS（production 請使用 TLS） |
| Client ID | `zqs:<device_id>` — ACL webhook 可以綁定此值 |
| Username | 註冊時發放，例如 `dev-demo-ZQS-BESS-0001` |
| Password | 註冊時發放，**只顯示一次** |
| Keepalive | 建議 45 s |
| Clean session | `false`，讓 QoS 1 的 downlink 能撐過短暫斷線 |
| QoS | telemetry、status、event、alarm 與命令一律為 1 |

`device_id` 在整個平台**全域唯一**，因為 topic 中不含租戶區段。請使用序號或
MAC address。允許字元：`A-Z a-z 0-9 . _ -`，長度 3–64 字元，不可含 MQTT
萬用字元。

### Last will and testament（必要）

請在**連線時**就註冊 LWT，突然斷電才看得出來：

- Topic: `energy/devices/{device_id}/status`
- Retain: `true`
- QoS: `1`
- Payload: `{"status":"offline","reason":"lwt"}`

連線成功後立即發布對應的 `{"status":"online", ...}`。

---

## 2. Topics

Root 可透過 `MQTT_TOPIC_ROOT` 設定，預設為 `energy/devices`。

| 方向 | Topic | 用途 |
| --- | --- | --- |
| uplink | `energy/devices/{device_id}/telemetry` | 量測值 |
| uplink | `energy/devices/{device_id}/status` | 上線／離線、firmware、位置 |
| uplink | `energy/devices/{device_id}/event` | 操作記錄項目 |
| uplink | `energy/devices/{device_id}/alarm` | 裝置偵測到的故障 |
| uplink | `energy/devices/{device_id}/control/ack` | 命令回覆 |
| downlink | `energy/devices/{device_id}/control` | 伺服器下達的命令 |

裝置只能發布到自己的 topic 子樹，也只能訂閱自己的 `control` topic；broker
透過 ACL webhook 強制執行這項限制。

---

## 3. Payload

所有 payload 都是 UTF-8 JSON 物件，最大 256 KB。未知的額外欄位會被接受並
忽略，因此日後新增欄位不會讓舊版伺服器出錯。

### 3.1 時間戳記

`ts` 接受下列任一形式：

- epoch **秒**、**毫秒**、**微秒**或**奈秒**（以數值大小判斷是哪一種——建議
  使用毫秒）；
- ISO-8601 文字，例如 `2026-06-01T09:15:00Z`；未帶時區位移的字串視為 UTC。

防護界線：超過**未來 5 分鐘**或早於**過去 7 天**的時間戳記會被拒絕。
`status`、`event`、`alarm` 與 `control/ack` 可以省略 `ts`，此時伺服器改用自己
的接收時間。`telemetry` **必須**帶 `ts`。

若裝置沒有可靠的時鐘，請使用 `sync_time` 命令，或在非 telemetry 的訊息上省略
`ts`，不要送出錯誤的值。

### 3.2 Telemetry（遙測）

兩種可互換的格式，選在 LabVIEW 裡比較好組出來的那一種。

**Dictionary 形式** — 所有 metric 共用一個時間戳記：

```json
{
  "ts": 1780000000000,
  "seq": 12345,
  "metrics": {
    "battery_soc": 78.2,
    "battery_power_w": -125000,
    "battery_temperature_c": 31.4,
    "pcs_state": "charge"
  }
}
```

**List 形式** — 每筆讀值各自帶時間戳記，適合在斷網後回補緩衝區的資料：

```json
{
  "ts": 1780000000000,
  "readings": [
    {"metric": "grid_power_w", "value": 214500, "ts": 1780000000000},
    {"metric": "grid_power_w", "value": 218900, "ts": 1780000005000}
  ]
}
```

| 欄位 | 型別 | 必要 | 說明 |
| --- | --- | --- | --- |
| `ts` | number/string | 是 | 見 3.1 |
| `seq` | integer | 否 | 單調遞增計數器，有助於診斷資料缺口 |
| `metrics` | object | 二擇一 | `{metric_key: value}` |
| `readings` | array | 二擇一 | `[{metric, value, ts?, quality?}]` |
| `meta` | object | 否 | 自由格式的附帶資訊 |

規則：

- metric key 為小寫 `snake_case`，≤ 64 字元；
- 值可以是數字、boolean（存成 1/0）、字串或 `null`；
- `NaN` 與 `Infinity` 會被拒絕——「沒有讀值」請送 `null`；
- 每則訊息最多 512 筆讀值；
- 重送相同的 `(device, metric, ts)` 是安全的：伺服器只會保留一列，因此在不
  確定是否送達時重試，不會重複計算。

metric catalogue（`GET /api/metrics`）列出所有內建的 key——與表後儲能相關的
部分見 §7。

### 3.3 Status（狀態）

```json
{
  "status": "online",
  "ts": 1780000000000,
  "reason": "boot",
  "firmware": "2.1.4",
  "hardware": "PCS-500K rev C",
  "ip": "10.20.30.40",
  "rssi": -63,
  "location": {
    "latitude": 25.0339,
    "longitude": 121.5645,
    "address": "No. 7, Sec. 5, Xinyi Rd, Taipei"
  }
}
```

`status` 為 `online` 或 `offline`，也是唯一的必填欄位。提供 `location` 時會
覆蓋地圖上場域本身的座標，伺服器並會記錄這個位置的來源。

發布 `status` 時請設為 **retained**，讓重新連線的 console 能看到當前狀態。
伺服器會忽略比已記錄的最後一次狀態轉換更舊的 retained 訊息，因此被重播的
LWT 不會把運作中的裝置誤判為離線。

### 3.4 Event（操作記錄）

```json
{
  "ts": 1780000000000,
  "level": "warning",
  "code": "E0231",
  "message": "Cooling fan speed below threshold",
  "data": {"fan_rpm": 820, "expected_rpm": 1200}
}
```

`level` ∈ `debug | info | notice | warning | error | critical`（預設 `info`）。

### 3.5 Alarm（警報）

```json
{
  "ts": 1780000000000,
  "code": "E0500",
  "severity": "major",
  "message": "Insulation resistance low",
  "active": true,
  "details": {"resistance_kohm": 41}
}
```

`severity` ∈ `info | warning | major | critical`。以相同的 `code` 搭配
`"active": false` 送出即可解除——伺服器會把對應的未結案 alert 標記為已解決。
警報持續有效期間，重複送出只會累加它的發生次數。

### 3.6 命令回覆（acknowledgement）

```json
{
  "command_id": "0f9d7a1c-4c1a-4e0e-9a7d-8f2b1c3d4e5f",
  "status": "succeeded",
  "ts": 1780000000000,
  "message": "",
  "result": {"applied_limit_w": 400000}
}
```

`status` ∈ `accepted | rejected | succeeded | failed`。若執行需要一段時間，
收到命令時先送 `accepted`，完成後再送 `succeeded` 或 `failed`。在終態之後才
抵達的 `accepted` 會被忽略，因此順序錯亂不會造成問題。

### 3.7 上線宣告（attributes，可選）

在 birth message（`{"status":"online"}` 那一則）的 payload 裡可以額外帶一個
`attributes` 物件，宣告這台設備是什麼、能做什麼。一般的狀態變更不必重複。

```json
{
  "status": "online",
  "ts": 1780000000000,
  "firmware": "2.1.4",
  "attributes": {
    "schema_version": 1,
    "category": "pcs",
    "manufacturer": "Acme Power",
    "model": "PCS-50K",
    "serial_number": "SN-2026-000123",
    "capabilities": {
      "can_charge": true,
      "can_discharge": true,
      "can_export": true,
      "is_dispatchable": true
    },
    "ratings": {
      "rated_power_kw": 50.0,
      "rated_energy_kwh": 100.0,
      "min_soc_percent": 10.0,
      "max_soc_percent": 90.0
    }
  }
}
```

| 欄位 | 型別 | 必要 | 說明 |
| --- | --- | --- | --- |
| `schema_version` | integer | 是 | 目前為 `1`。不認得的版本會被記錄並忽略 |
| `category` | string | 否 | `battery`、`pcs`、`pv_inverter`、`meter`、`load`、`generator`、`ev_charger`、`controller`、`sensor`、`gateway`、`other` |
| `manufacturer` / `model` / `serial_number` | string | 否 | 供操作者比對機器銘牌 |
| `capabilities.*` | boolean | 否 | 四個能力旗標；缺省代表「未宣告」，不是 `false` |
| `ratings.*` | number | 否 | 銘牌與韌體自己的限值 |

**這些值不會自動生效。** 伺服器把宣告原封不動存起來、與目前設定比對差異，
然後等待管理者在 console 上接受或拒絕。在被接受之前，它完全不影響這台設備被
允許執行哪些命令——一台被入侵的機器無法靠改口宣告替自己解鎖充電權限。

宣告內容與上次完全相同時不會重複產生待審核項目，所以每次重連都發是安全的。

---

## 4. 命令（downlink）

裝置訂閱 `energy/devices/{device_id}/control`，會收到：

```json
{
  "command_id": "0f9d7a1c-4c1a-4e0e-9a7d-8f2b1c3d4e5f",
  "name": "set_power_limit",
  "params": {"limit_w": 400000},
  "issued_at": 1780000000000,
  "expires_at": 1780000060000,
  "reply_to": "energy/devices/ZQS-BESS-0001/control/ack"
}
```

預期行為：

1. 忽略 `expires_at` 已經過期的命令——伺服器已將它標記為過期，不再等待回覆。
2. 在本地也要驗證 `params`；伺服器雖然已依 blueprint 檢查過，裝置仍是最後
   一道防線。
3. 把回覆發布到 `reply_to`，並原樣回傳 `command_id`。
4. 遇到重複的 `command_id` 視為重送，直接重發前一次的回覆，不要執行兩次。

可用的命令來自裝置的 blueprint；`manage.py bootstrap` 內建的預設值如下：

| Blueprint | 命令 | 參數 |
| --- | --- | --- |
| `bess-pcs` | `set_power_limit` | `limit_w` 0…5 000 000 |
| | `set_power_setpoint` | `power_w` ±5 000 000、`ramp_s` 0…3600 |
| | `set_mode` | `mode` ∈ idle/charge/discharge/auto/standby |
| | `set_soc_limits` | `min_soc`、`max_soc` 0…100 |
| | `emergency_stop` | — |
| | `reboot` | — |
| `smart-meter` | `set_report_interval` | `interval_s` 1…3600 |
| `pv-inverter` | `set_export_limit` | `limit_w` 0…5 000 000 |
| | `set_output_enabled` | `enabled` boolean |
| `ems-controller` | `set_strategy` | `strategy`、`target_kw` |
| | `sync_time` | `epoch_ms` |
| `ev-charger` | `set_current_limit` | `limit_a` 0…500 |
| | `stop_session` | — |

---

## 5. 建議的裝置行為

**發布頻率。** 功率類訊號 1–10 s，SOC 與溫度 30–60 s，狀態字串則在變動時
發布。不要為了省頻寬而在裝置端節流：伺服器的 recording policy 已經決定哪些
要存，而它需要完整的資料流才能正確評估 alert。

**緩衝。** 本地至少保留一小時的樣本。重新連線後，以 list 形式搭配原始時間
戳記回補；唯一性規則讓回補具備 idempotent 特性，因此資料重疊也不會有問題。

**Backoff。** 以 1 s 到 60 s 之間的 exponential backoff 加上 jitter 重連。
認證失敗後不要密集重連——憑證不會自己修好，broker 也會對你限流。

**時鐘。** 盡可能透過 NTP 校時。超出容許誤差範圍的時間戳記會被丟棄，而且從
裝置的角度看不到任何錯誤。

---

## 6. LabVIEW 實作要點

- 任何 MQTT toolkit 都可以。發布端只需要：帶 LWT 連線、以 QoS 1 發布字串
  payload、訂閱一個 topic。
- 用內建的 **Flatten To JSON** 組 JSON，或者針對固定的 telemetry 格式直接以
  字串串接——payload 小而規律。
- 在應用程式的生命週期內維持單一持續連線，不要每次發布都重新連線再斷線。
- 採用 producer/consumer queue：擷取迴圈 → queue → 發布迴圈。發布迴圈斷線
  時，把 queue 寫到磁碟，稍後再回補。
- 在獨立的事件迴圈處理 control topic，長時間執行的命令才不會阻塞 telemetry
  的發布。

最精簡的 telemetry payload，以格式字串表示：

```
{"ts":%d,"metrics":{"battery_soc":%.2f,"battery_power_w":%.1f}}
```

---

## 7. 表後（behind-the-meter）儲能的內建 metric key

| Key | 單位 | 意義 |
| --- | --- | --- |
| `grid_power_w` | W | 併接點量測；**+ 為輸入，− 為輸出** |
| `grid_voltage_v` | V | |
| `grid_current_a` | A | |
| `grid_frequency_hz` | Hz | |
| `grid_import_energy_kwh` | kWh | 累計計數器 |
| `grid_export_energy_kwh` | kWh | 累計計數器 |
| `load_power_w` | W | 場域負載，恆 ≥ 0 |
| `pv_power_w` | W | 發電功率，恆 ≥ 0 |
| `pv_energy_kwh` | kWh | 累計計數器 |
| `battery_power_w` | W | **+ 為放電，− 為充電** |
| `battery_soc` | % | 0–100 |
| `battery_soh` | % | 0–100 |
| `battery_voltage_v` | V | |
| `battery_current_a` | A | |
| `battery_temperature_c` | °C | |
| `battery_charge_energy_kwh` | kWh | 累計計數器 |
| `battery_discharge_energy_kwh` | kWh | 累計計數器 |
| `pcs_state` | — | 字串狀態，例如 `idle`/`charge`/`discharge` |
| `pcs_fault_code` | — | 廠商自訂代碼 |

正負號的約定很重要：energy aggregator 是依號誌來區分輸入與輸出、充電與放電。
若硬體採用相反的約定，請在該能源資產上設定 **Invert sign**，不要去改裝置的
firmware。

其他 key 也一律接受——可透過 `POST /api/metrics` 定義，讓 console 知道它的
單位與標籤，或就讓它以未標記的形式通過。

---

## 8. 沒有硬體時的快速驗證

```bash
python manage.py simulate_device --device ZQS-BESS-0001 --profile battery --interval 5
```

這會發布與上述完全相同的 payload，因此也可以當作 wire format 的參考實作。
