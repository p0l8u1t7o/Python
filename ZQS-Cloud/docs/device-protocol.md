# ZQS Cloud 裝置通訊協定：Sparkplug B

裝置端實作與平台通訊所需的一切。

本平台遵循 **Eclipse Sparkplug B 規範**（namespace `spBv1.0`）。這代表兩件事：

- 標示「**規範要求**」的部分不是 ZQS 的偏好，是 Sparkplug 規範本身的規定，改不了；
- 照著做的設備可以直接接上任何 Sparkplug 主機（Ignition、HiveMQ、Cirrus Link
  等），不只是這個平台。

伺服器會驗證本文描述的每一個欄位，不符合的一律拒絕，因此請把本文件視為契約。

---

## 1. 三層位址

Sparkplug 的位址有三層：

```
spBv1.0/{group_id}/{訊息型別}/{edge_node_id}/{device_id}
        └group     └型別      └邊緣節點       └設備
```

| 層級 | 是什麼 | 誰決定 |
| --- | --- | --- |
| `group_id` | 你的組織代碼 | 平台發放，例如 `demo` |
| `edge_node_id` | **一條 MQTT 連線** | 平台發放 |
| `device_id` | 掛在該連線下的一台設備 | 平台發放 |

**最重要的一句話：一條 MQTT 連線 = 一個 edge node。** 不是一台設備一條連線。

現場典型的樣子是一台 EMS 網關對外講 MQTT、對內講 Modbus，底下掛著電池、電錶、
變流器。那台網關就是 edge node，底下每一台設備各是一個 `device_id`：

```
EdgeNode  ZQS-GW-0001          ← 一組帳密、一條連線、一個 seq 計數器
  ├ Device ZQS-BESS-0001
  ├ Device ZQS-METER-0001
  └ Device ZQS-PV-0001
```

設備自己會講 MQTT、直接連上來也可以，作法見 §1.2。

> **絕對不要讓兩個行程用同一個 `edge_node_id` 連線。** 它們會共用一個 seq 計數器
> 卻各自遞增，主機看到的是永遠對不上的序號；而且 MQTT 會讓後連上的把先連上的
> 踢掉，兩邊無限互踢。要跑多個行程，就申請多個 edge node。

### 1.1 沒有網關的設備怎麼做

一台自己會講 MQTT 的設備——例如韌體裡就有 MQTT client 的 PCS、或一台獨立的電錶
——不需要任何網關。**它自己就是 edge node，同時也是掛在自己底下的那台設備。**

平台在註冊時就會自動建立承載那條連線的節點，所以操作者那邊只是「新增一台設備」，
不必先建立什麼。你會拿到：

| 你拿到的東西 | 值 |
| --- | --- |
| `group_id` | 組織代碼，例如 `demo` |
| `edge_node_id` | 通常與設備 id 相同 |
| `device_id` | 你的設備 id |
| Username | `node-<group_id>-<edge_node_id>` |
| Password | 只顯示一次 |

以 `ZQS-BESS-0001` 為例，位址是 `demo/ZQS-BESS-0001/ZQS-BESS-0001`，topic 長這樣：

```
spBv1.0/demo/NBIRTH/ZQS-BESS-0001                  ← 節點宣告
spBv1.0/demo/DBIRTH/ZQS-BESS-0001/ZQS-BESS-0001    ← 設備宣告
spBv1.0/demo/DDATA/ZQS-BESS-0001/ZQS-BESS-0001     ← 讀值
spBv1.0/demo/NDEATH/ZQS-BESS-0001                  ← 遺言
訂閱 spBv1.0/demo/NCMD/ZQS-BESS-0001
訂閱 spBv1.0/demo/DCMD/ZQS-BESS-0001/+
```

**你要做的事跟網關完全一樣，一個步驟都不能省**，只是每一種訊息各只有一則：

1. 註冊 NDEATH 遺言（帶 `bdSeq`）
2. 連線、訂閱 NCMD 與 DCMD
3. 發 NBIRTH（`seq = 0`）
4. 發**一則** DBIRTH
5. 之後發 DDATA

> **兩個常見的誤解。**
>
> **「我只有一台設備，可以只發 NBIRTH，跳過 DBIRTH 嗎?」** 不行。節點層級的
> 讀值（NDATA）平台不儲存——這個系統的資料模型裡沒有「屬於一條連線而不屬於設備」
> 的量測。你的讀值必須掛在 device 層，所以必須先有 DBIRTH。
>
> **「兩層 id 一樣，是不是很多餘?」** 在單機的情況下看起來是。但它讓同一份韌體
> 在之後被裝到網關後面時完全不用改：位址多了一層，訊息流程一模一樣。

想省事的話，**§14 的模擬器就是照這個模式跑的**，可以直接拿來對照：

```bash
python manage.py simulate_device --device ZQS-BESS-0001 --profile battery
```

### 1.2 允許的字元

規範保留 `+`、`#`、`/` 給 topic 結構使用。平台再嚴格一點：`A-Z a-z 0-9 . _ -`，
長度 3–64 字元。需要百分比編碼才能放進 topic 的 id，是沒有人 grep 得到的 id。

---

## 2. 連線

| 項目 | 值 |
| --- | --- |
| Protocol | MQTT 3.1.1 或 5.0 |
| Broker | EMQX |
| Port | `1883` 未加密，`8883` TLS（production 請使用 TLS） |
| Client ID | `zqs:<edge_node_id>` — ACL webhook 可以綁定此值 |
| Username | 註冊時發放，格式 `node-<group_id>-<edge_node_id>`，例如 `node-demo-ZQS-GW-0001` |
| Password | 註冊時發放，**只顯示一次**。用途見 §11 |
| Keepalive | 建議 45 s。這個值直接決定斷線多久才被發現，見 §10 |
| **Clean session** | **`true`（規範要求）** |
| QoS | 見 §2.2 |

### 2.1 Clean session 必須是 true

規範禁止保留 session，這一項不是可選的。理由很具體：持久 session 會讓 broker 把
斷線前排隊的命令在重連後補送，而那時節點已經發過新的 NBIRTH、重新宣告過自己的
狀態了。那道命令會被套用在一份已經作廢的狀態上。

- MQTT 3.1.1：`Clean Session = true`
- MQTT 5：`Clean Start = true` 且 `Session Expiry Interval = 0`

### 2.2 QoS 與 retain 是規定死的

| 訊息 | QoS | Retain |
| --- | --- | --- |
| NBIRTH / DBIRTH | 0 | false |
| NDATA / DDATA | 0 | false |
| DDEATH | 0 | false |
| **NDEATH（遺言）** | **1** | **false** |
| NCMD / DCMD（主機發） | 0 | false |
| STATE（主機發） | 1 | **true** |

兩個看起來奇怪但不是的地方：

**為什麼全是 QoS 0?** Sparkplug 的順序保證來自 payload 裡的 `seq` 計數器，訊息
遺失是靠「要求重生」補救，不是靠 broker 重送。QoS 1 買到的是重複訊息，不是安全。

**為什麼遺言不能 retained?** retained 的 NDEATH 會活得比它描述的那次連線更久。
之後任何訂閱者一連上來就會被告知這個節點死了——即使它早就回來並重新宣告過。

---

## 3. Payload：Protocol Buffers

**Sparkplug B 的 payload 是 Google Protocol Buffers 編碼的，不是 JSON。** 這是
規範強制的，也是能跟其他 Sparkplug 系統互通的原因。

schema 檔在 `services/sparkplug/sparkplug_b.proto`（逐字取自 Eclipse Tahu 專案，
是規範的一部分）。LabVIEW 端怎麼做見 §9。

### 3.1 Payload 結構

```protobuf
message Payload {
  optional uint64 timestamp = 1;   // epoch 毫秒
  repeated Metric metrics  = 2;
  optional uint64 seq      = 3;    // 0–255
  optional string uuid     = 4;
  optional bytes  body     = 5;
}

message Metric {
  optional string name      = 1;
  optional uint64 alias     = 2;
  optional uint64 timestamp = 3;
  optional uint32 datatype  = 4;
  optional bool   is_null   = 7;
  oneof value {
    uint32 int_value     = 10;
    uint64 long_value    = 11;
    float  float_value   = 12;
    double double_value  = 13;
    bool   boolean_value = 14;
    string string_value  = 15;
    // ...
  }
}
```

`timestamp` 一律是 **epoch 毫秒**。規範只認這一種，不接受秒、微秒或 ISO 字串。

防護界線：超過**未來 5 分鐘**或早於**過去 7 天**的時間戳記會被拒絕。payload 層的
時間戳記不合理會整則退回；單一 metric 的時間戳記不合理則只丟掉那一個 metric。

### 3.2 資料型別

`datatype` 是決定怎麼讀回 `oneof` 那幾個欄位的唯一依據。填錯的話 −5 °C 會變成
4294967291。

| 值 | 型別 | 放在哪個欄位 |
| --- | --- | --- |
| 1/2/3 | Int8 / Int16 / Int32 | `int_value`（二補數） |
| 4 | Int64 | `long_value`（二補數） |
| 5/6/7 | UInt8 / UInt16 / UInt32 | `int_value` |
| 8 | UInt64 | `long_value` |
| 9 | Float | `float_value` |
| 10 | Double | `double_value` |
| 11 | Boolean | `boolean_value` |
| 12 | String | `string_value` |
| 13 | DateTime | `long_value`（epoch 毫秒） |

**沒有讀值時請設 `is_null = true`**，不要送 0。「感測器沒讀到」和「感測器讀到 0」
是兩件事，整個能量積分都靠這個區別。

### 3.3 seq：每一則訊息 +1

除了 NDEATH 以外，**每一則**訊息都要帶 `seq`，從 NBIRTH 的 0 開始，每則加一，到
255 之後回到 0。

主機就是靠這個發現訊息遺失的。發現缺號時它會要求重生（§7），不會猜。

NDEATH 沒有 `seq`，因為它是 broker 在一個節點無法預知的時間點代發的。

> **多執行緒的陷阱。** 如果採集迴圈和命令回覆迴圈都會發布，序號的**配置與送出必須
> 在同一個鎖裡**。只鎖住計數器是不夠的：兩個執行緒可以拿到 7 和 8，卻以 8、7 的
> 順序到達 socket，主機分不出這跟遺失訊息有什麼差別。這是實作 Sparkplug 最常踩的
> 坑之一，本專案的參考實作也踩過。

### 3.4 alias：省頻寬的關鍵

BIRTH 時為每個 metric 指派一個數字 `alias`，之後的 DATA 就**只帶 alias、不帶
名稱**：

```
DBIRTH:  name="battery_soc"  alias=1  datatype=10  double_value=62.0
DDATA:                       alias=1              double_value=78.5
```

alias 在節點內（node metric）或設備內（device metric）唯一。

沒指派 alias 也能運作，平台照收，只是每則訊息都要重複完整名稱——Sparkplug 省
頻寬的效果就沒了。

---

## 4. 訊息型別

| 型別 | 方向 | 什麼時候 |
| --- | --- | --- |
| `NBIRTH` | 上行 | 連線後**第一則**。宣告節點，`seq` 歸零 |
| `NDEATH` | 上行 | 註冊為遺言。節點失聯時由 broker 代發 |
| `NDATA` | 上行 | 節點層級的數值（本平台不儲存，見 §4.4） |
| `DBIRTH` | 上行 | 每台設備一則，宣告它提供的所有 metric |
| `DDEATH` | 上行 | 某台設備失聯，但節點還在 |
| `DDATA` | 上行 | 設備的量測值、警報、事件、命令回覆 |
| `NCMD` | 下行 | 主機寫入節點層級的可寫 metric |
| `DCMD` | 下行 | 主機寫入設備層級的可寫 metric |
| `STATE` | 主機發 | 主機自己的死活，見 §8 |

### 4.1 連線順序（順序不能換）

1. 準備 NDEATH payload（帶 `bdSeq`），在 **CONNECT 封包裡**註冊為遺言。連上之後
   才設的遺言，broker 從來沒收到過。
2. 連線。
3. **訂閱** `spBv1.0/{group}/NCMD/{node}` 與 `spBv1.0/{group}/DCMD/{node}/+`。
   先訂閱再宣告，否則中間空檔進來的命令會漏掉。
4. 發布 **NBIRTH**（`seq = 0`，帶 `bdSeq`，帶 `Node Control/Rebirth`）。
5. 每台設備各發一則 **DBIRTH**。
6. 之後才開始發 DDATA。

> **在 NBIRTH 出去之前不可以發布任何東西。** 這不只是規範問題：實務上第一則 DDATA
> 很容易跟 birth 搶跑，因為多數 MQTT 函式庫的「已連線」回呼跑在另一個執行緒上。
> 結果是 seq 變成 0、0、1，主機一連上就判定序號有問題。

### 4.2 bdSeq：讓死亡對得上出生

`bdSeq` 是一個 metric，**每次連線加一**（0–255 循環），同時出現在 NBIRTH 和 NDEATH
裡，而且兩者的值必須相同。

它解決的問題是：一則姍姍來遲的遺言，可能在節點已經重連之後才被處理。平台比對
`bdSeq`，發現這則死亡屬於一個已經被取代的 session，就會忽略它——否則剛回來的節點
會被自己上一次的遺言打死。

```
NBIRTH  bdSeq=5   ← 這次連線
NDEATH  bdSeq=5   ← 遺言，對應同一次
```

### 4.3 BIRTH 要帶什麼

DBIRTH 的定義是「這台設備提供的**全部** metric」，不是抽樣。而且要帶**當下的
數值**，不只是型別——主機剛連上就有東西可以顯示。

BIRTH 沒列出的 alias 會被平台刪除。這是刻意的：出生宣告是完整清單，沒被列到的就是
已經退役了，留著它會讓舊的對應表去解讀新的訊息。

### 4.4 NDATA

平台接受但不儲存節點層級的量測值。這個系統的資料模型裡沒有「屬於一條連線而不屬於
設備」的量測。節點的韌體版本、IP 這類資訊請放在 NBIRTH 的 `Properties/` metric 裡
（§5.3）。

---

## 5. Metric 命名規則（ZQS profile）

Sparkplug 規定 topic、編碼與狀態機，但**刻意不規定 metric 叫什麼**。以下是本平台的
約定。

| 前綴 | 意義 |
| --- | --- |
| `Properties/…` | 身分與中繼資料（韌體、型號、座標） |
| `Capabilities/…` | 設備宣稱自己能做什麼 |
| `Ratings/…` | 銘牌額定值 |
| `Alarm/<code>` | 故障，boolean：true 觸發、false 解除 |
| `Event/<code>` | 操作記錄，string |
| `Command/…` | 命令關聯，見 §6 |
| `Node Control/…` | 規範定義的節點可寫控制 |
| `Device Control/…` | 設備可寫控制 |
| 其他 | **量測值**，進時序資料庫 |

### 5.1 量測值的命名

平台的 metric 目錄用小寫 `snake_case`（`battery_soc`、`grid_power_w`）。
`Battery/SOC`、`battery_soc`、`Battery SOC` 都會正規化成同一個 key，所以兩種寫法
都行——但同一台設備請固定用一種。

內建的 metric key 清單見 §12。

### 5.1.1 帶上單位，就會即插即用

在 DBIRTH 的每個量測 metric 上加一個 `unit` property：

```
name       = "stack_voltage_v"
alias      = 7
datatype   = Double
properties = { unit: "V" }
```

平台看到一個目錄裡沒有的 key 時，**會直接用出生宣告把它建起來**：單位、資料型別、
彙總方式全部從宣告推出來。結果是一台從來沒有人設定過的設備，一連上來圖表就有座標
軸標籤，不需要任何前置作業。

可用的 property：

| property | 作用 |
| --- | --- |
| `unit` | 單位字串，例如 `W`、`kWh`、`degC`、`%` |
| `kind` | `gauge`（預設）、`counter`、`state` |
| `description` | 說明文字 |
| `display_name` | 顯示名稱，省略時用 metric 名稱 |
| `counter_max` | 累計值溢位翻轉的上限，知道的話請填 |

兩個推論規則值得知道：

- 單位是 `kWh`、`Wh`、`m3` 這類累計單位時，**自動視為 counter**（取差值而不是積
  分）。搞錯這個會讓能量數字整個錯掉，而單位是出生宣告裡唯一的線索。想推翻就明確
  填 `kind`。
- 單位是 `%` 或 `degC` 時會套用一個寬鬆的合理範圍，超出的讀值照存但標記為可疑。

**這只會建立標籤，不會授予任何權限。** 已經存在的 metric 定義**永遠不會被覆蓋**
——否則一次韌體更新就能悄悄改掉一堆告警規則所依賴的 metric。能力與額定值仍然走
§5.2 的宣告流程，要人在 console 上接受。

### 5.2 上線宣告就是 DBIRTH

設備的自我宣告不需要額外的欄位或訊息：BIRTH 本來就定義為「這台設備提供的全部
東西」，宣告直接就是其中幾個 metric。

```
Properties/Schema Version    Int32    1          （選填，見下）
Properties/Category          String   "battery"
Properties/Manufacturer      String   "Acme Power"
Properties/Model             String   "PCS-50K"
Properties/Serial Number     String   "SN-2026-000123"
Capabilities/Can Charge      Boolean  true
Capabilities/Can Discharge   Boolean  true
Capabilities/Can Export      Boolean  true
Capabilities/Is Dispatchable Boolean  true
Ratings/Rated Power kW       Double   50.0
Ratings/Rated Energy kWh     Double   100.0
Ratings/Min SOC Percent      Double   10.0
Ratings/Max SOC Percent      Double   90.0
```

`Properties/Schema Version` 是選填的。metric 的**名字**就是 schema，而名字是這份
profile 定義的，所以版本屬於 profile 而不是設備。省略代表「用目前這一版」；填了一個
平台不認得的版本，宣告會被記錄下來然後忽略——因為那代表同樣的名字在對方那裡可能是
別的意思。

**這些值不會自動生效。** 伺服器把宣告原封不動存起來、與目前設定比對差異，然後等待
管理者在 console 上接受或拒絕。在被接受之前，它完全不影響這台設備被允許執行哪些
命令——一台被入侵的機器無法靠改口宣告替自己解鎖充電權限。

宣告內容與上次完全相同時不會重複產生待審核項目，所以每次重連都發是安全的——而
重連會相當頻繁地重發 BIRTH，這一點很重要。

### 5.3 節點層級的 Properties

放在 NBIRTH 裡：

```
Properties/Firmware  String  "2.1.4"
Properties/Hardware  String  "GW-500 rev C"
Properties/IP        String  "10.20.30.40"
Properties/RSSI      Int32   -63
```

設備層級的位置資訊放在 DBIRTH 裡：

```
Properties/Latitude   Double  25.0339
Properties/Longitude  Double  121.5645
Properties/Address    String  "台北市信義路五段 7 號"
```

提供 `Latitude`/`Longitude` 會覆蓋地圖上場域本身的座標。

### 5.4 警報

`Alarm/<code>`，Boolean。true 觸發，false 解除。嚴重度與訊息放在 metric 的
`properties` 裡：

```
name       = "Alarm/E0500"
datatype   = Boolean
value      = true
properties = { severity: "major", message: "Insulation resistance low",
               resistance_kohm: 41 }
```

`severity` ∈ `info | warning | major | critical`。以相同的 `code` 送 `value = false`
即可解除；警報持續有效期間重複送出只會累加發生次數。

### 5.5 事件（操作記錄）

`Event/<code>`，String，值就是訊息本文：

```
name       = "Event/E0231"
datatype   = String
value      = "Cooling fan speed below threshold"
properties = { level: "warning", fan_rpm: 820 }
```

`level` ∈ `debug | info | notice | warning | error | critical`（預設 `info`）。

### 5.6 只想顯示、不想留存的值

在 metric 上設 `is_transient = true`。平台會顯示它、拿它評估警報，但不寫進時序
資料庫。適合瞬間狀態這種存了也沒有意義的東西。

---

## 6. 命令（downlink）

Sparkplug 把命令模型化為「寫入 metric」，而且**沒有定義回覆訊息**——確認就是設備把
那個 metric 回報回來。

這對設定值夠用，但對稽核軌跡不夠：無法回答「哪一道命令沒有被回應」。所以本 profile
在標準之上多帶一個關聯 metric。這仍然完全合規——Sparkplug 不規定 metric 叫什麼。

### 6.1 收到的 DCMD

Topic：`spBv1.0/{group}/DCMD/{node}/{device}`

```
Command/ID        String    "0f9d7a1c-4c1a-4e0e-9a7d-8f2b1c3d4e5f"
Command/Name      String    "set_power_limit"
Command/Expires   DateTime  1780000060000
Command/limit_w   Int64     400000
```

參數以 `Command/<參數名>` 攜帶。

### 6.2 回覆

發一則 **DDATA**（不是別的型別），帶：

```
Command/ID           String  "0f9d7a1c-…"    ← 原樣帶回
Command/Status       String  "succeeded"
Command/Message      String  ""              ← 選填
Command/Result/<key> …                       ← 選填
```

`Command/Status` ∈ `accepted | rejected | succeeded | failed`。

執行需要一段時間的話，收到命令時先回 `accepted`，完成後再回 `succeeded` 或
`failed`。終態之後才抵達的 `accepted` 會被忽略，所以順序錯亂不會造成問題。

### 6.3 預期行為

1. 忽略 `Command/Expires` 已經過期的命令——伺服器已將它標記為過期，不再等待回覆。
2. 在本地也要驗證參數；伺服器雖然已依 blueprint 檢查過，裝置仍是最後一道防線。
3. 遇到重複的 `Command/ID` 視為重送，直接重發前一次的回覆，不要執行兩次。

### 6.4 可用的命令

來自裝置的 blueprint；`manage.py bootstrap` 內建的預設值如下：

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

## 7. 重生（Rebirth）：唯一的復原路徑

**這一節不是選配。** 沒有實作它的設備，在第一次掉訊息之後就再也對不齊了。

NBIRTH **必須**宣告一個可寫的 boolean metric：

```
Node Control/Rebirth   Boolean   false
```

主機在下列情況會寫入 `true`：

- `seq` 出現缺號（代表有訊息遺失，對應表可能已經不準）；
- 收到一個對應表裡沒有的 alias（代表主機沒看到那次 BIRTH——例如主機比設備晚啟動）；
- 操作者在 console 上手動要求。

**收到之後要做的事：重新發一次完整的 NBIRTH（`seq` 歸零）與所有 DBIRTH。**

平台對同一個節點的重生要求有 30 秒冷卻，所以一連串亂序訊息只會換來一次要求，不會
變成風暴。

設備層級的 `Device Control/Rebirth` 同理，走 DCMD。

---

## 8. 主機狀態（STATE）

平台會在 `spBv1.0/STATE/{host_id}` 發布自己的死活，**retained、QoS 1**，內容是
UTF-8 JSON（這是命名空間裡唯一不是 protobuf 的東西，為的是讓任何工具都讀得懂）：

```json
{"online": true, "timestamp": 1780000000000}
```

預設 `host_id` 是 `zqs-cloud`，可用 `SPARKPLUG_HOST_ID` 設定。

設備可以訂閱它，用來判斷「現在發出去有沒有人在聽」。不訂閱也可以，這不是必要的。

---

## 9. LabVIEW 實作要點

protobuf 沒辦法像 JSON 那樣用字串串接組出來，這是設備端最大的一項工作。有三條路：

### 路線 A：現成的 protobuf toolkit（建議）

LabVIEW 有幾套第三方 protobuf 實作（VIPM 上搜尋 protobuf）。把
`services/sparkplug/sparkplug_b.proto` 丟進去產生型別即可。長期最省事，尤其是之後
要用到 DataSet、Template 這些進階型別時。

### 路線 B：手寫編碼器

Sparkplug 實際用到的 protobuf wire format 只有三種：

| Wire type | 用在 |
| --- | --- |
| `0` varint | int / uint / bool / enum |
| `2` length-delimited | string / bytes / 巢狀 message |
| `1` 64-bit、`5` 32-bit | double / float |

每個欄位前面是一個 varint 的 key：`(欄位編號 << 3) | wire_type`。

以「一則帶單一 double metric 的 DDATA」為例：

```
Payload.timestamp (欄位1, varint)   → 0x08, varint(epoch_ms)
Payload.metrics   (欄位2, 長度限定) → 0x12, len, <Metric 的位元組>
  Metric.alias        (欄位2, varint) → 0x10, varint(alias)
  Metric.timestamp    (欄位3, varint) → 0x18, varint(epoch_ms)
  Metric.datatype     (欄位4, varint) → 0x20, 10        (Double)
  Metric.double_value (欄位13, 64bit) → 0x69, <8 bytes little-endian>
Payload.seq       (欄位3, varint)   → 0x18, varint(seq)
```

固定格式的 telemetry 只需要 varint 編碼與 8-byte double 兩個子 VI。實作完之後，
**一定要拿 §9.1 的參考實作對拍**。

### 路線 C：先跑通流程再換編碼

先用參考實作（Python）當作橋接，把整條鏈路跑通、確認位址與帳密都對，再回頭換掉編碼
層。這樣可以把「協定理解錯」和「編碼寫錯」兩類問題分開處理。

### 9.1 對拍用的參考實作

以下都是可以直接讀的完整實作：

| 檔案 | 是什麼 |
| --- | --- |
| `services/sparkplug/node.py` | 節點端的序號、alias、生死流程 |
| `services/harness/simulator.py` | 最精簡的正確設備 |
| `services/sparkplug/payload.py` | 編解碼 |

要產生一段標準 payload 來對拍：

```bash
python manage.py simulate_device --device ZQS-BESS-0001 --profile battery
```

### 9.2 其他實作要點

- 在應用程式的生命週期內維持**單一持續連線**，不要每次發布都重連。
- 採用 producer/consumer queue：擷取迴圈 → queue → 發布迴圈。發布迴圈斷線時，把
  queue 寫到磁碟，稍後再回補。
- 在獨立的事件迴圈處理命令 topic，長時間執行的命令才不會阻塞 telemetry。
- **但發布本身要序列化**，理由見 §3.3。

---

## 10. 離線判定：斷線後多久 console 會顯示離線

平台有**三條**獨立的路徑會把設備標成離線，走哪一條**由裝置端的實作決定**。

### 10.1 三條路徑

**路徑 A — 設備自己說。** 收到 NDEATH 或 DDEATH 就立刻寫入。

**路徑 B — broker 發遺言。** 節點沒有在 keepalive 期限內送出任何封包時，broker
判定連線已死並代為發布 NDEATH。MQTT 規格給 broker 的寬限是 **1.5 × keepalive**：
keepalive 45 s 就是最遲 **67.5 s**。

**路徑 C — 伺服器端的逾時掃描。** worker 內有一個每 **30 s** 跑一次的巡檢，把
「狀態仍是 online，但最後一次上行超過 `DEVICE_OFFLINE_GRACE_SECONDS`
（預設 **180 s**）」的設備翻成離線。這是 broker 也失聯時的最後防線。

### 10.2 實際數字

console 的設備清單每 **15 s** 重新拉一次，單一設備頁每 **5 s**。以下是加上輪詢後的
**最壞情況**：

| 情況 | 路徑 | console 顯示離線 |
| --- | --- | --- |
| 節點主動送 NDEATH | A | **≤ 15 s**（設備頁 ≤ 5 s） |
| 斷電、拔網路線——**且有註冊遺言** | B | **≤ 約 83 s**（67.5 + 15） |
| 正常送 `DISCONNECT` 關閉，但沒先送 NDEATH | C | **180–225 s** |
| 沒有註冊遺言 | C | **180–225 s** |
| broker 自己掛了 | C | **180–225 s**（所有設備一起） |

> **正常關機時遺言不會發。** MQTT 規格明訂：送出 `DISCONNECT` 封包正常關閉連線時，
> broker 會**丟棄** will message。所以計畫性關機、韌體更新重開、維護斷線，全都不會
> 觸發遺言。
>
> 因此在主動斷線之前，請**自己發一則 NDEATH**（以及每台設備的 DDEATH），再送
> `DISCONNECT`。否則這個節點在 console 上會維持「線上」直到逾時掃描把它撿走。

### 10.3 「離線」與「資料已過期」是兩件事

| 標示 | 依據 | 意思 |
| --- | --- | --- |
| **離線** | `status` | 收到過死亡訊息，或被逾時掃描翻掉 |
| **資料已過期** | `last_seen_at` 超過 180 s | 狀態還是「線上」，但已經很久沒講話 |

後者存在的理由是：連線活著不等於資料是新的。一台 MQTT 連線正常、PINGREQ 照送、但
採集迴圈卡死的設備，在 broker 眼中完全健康。

**任何一則上行都會重置這個計時器。** 所以：

> 即使數值完全沒有變化，也請**至少每 60 s** 送出一則 DDATA 當作心跳。只在數值變化
> 時才發布的設備，在穩態下會被標成資料已過期。

伺服器端的 recording policy 會決定哪些讀值要真的存進資料庫，所以高頻發布不會把資料
庫塞爆——不要為了省空間在裝置端節流。

---

## 11. Username 與 Password 是做什麼的

### 11.1 用途只有一個

這組帳密**只用來連上 MQTT broker**。它不是 API 帳號：不能呼叫 REST API、不能登入
console、不帶任何組織層級的權限。它回答的是「這條 MQTT 連線是不是那個 edge node」，
僅此而已。

**帳密屬於節點，不屬於設備。** 一台網關前置十二顆電錶，只登入一次；為了一條 TCP
連線發十二組密碼是做戲。

### 11.2 怎麼發放

| 時機 | 動作 |
| --- | --- |
| 註冊網關時 | `POST /api/edge-nodes` |
| 註冊直連設備時 | `POST /api/devices`（自動建立隱含節點並發憑證） |
| 事後輪替 | `POST /api/edge-nodes/{id}/credential` |

Password 是 24 bytes 的隨機字串，平台**只存雜湊值**。它在 API 回應裡出現的那一次是
唯一一次，之後沒有任何方式可以取回——包含平台管理者自己。遺失只能輪替。

輪替會讓舊密碼**立即失效**。請先確定手上有辦法把新密碼寫進設備，再按輪替。

### 11.3 broker 怎麼驗證

EMQX 不自己保存帳號。每一次 CONNECT，它都用 HTTP webhook 回頭問平台
（`POST /api/emqx/auth`）。直接後果是：**在 console 上停用一個節點，它下一次連線就
會被拒**，不需要改 broker 設定或重啟任何東西。

每一次 publish 與 subscribe 也同樣會問（`POST /api/emqx/acl`），強制執行三件事：

- topic 在 Sparkplug 命名空間裡；
- 其中的 `(group_id, edge_node_id)` 屬於這組憑證；
- 訊息型別的方向正確——節點可以發 NBIRTH/NDEATH/NDATA/DBIRTH/DDEATH/DDATA，只能
  訂閱 NCMD/DCMD。

第二項最重要：少了它，任何一組有效憑證都可以替鄰居發一則 NDEATH，把對方打下線。

### 11.4 Client ID pinning（選用）

設定 `allowed_client_id` 之後，即使帳密正確、client id 不符也會被拒絕。這是為了擋
「同一組帳密被複製到第二台機器」——兩台同時連線時 MQTT 會互踢，症狀是不斷重連，很
難查。沒設定就不檢查。

### 11.5 認證失敗時

**不要密集重連。** 密碼不會自己修好，而 broker 會對你限流。請用 1 s 到 60 s 的
exponential backoff 加 jitter。

| 原因 | 怎麼確認 |
| --- | --- |
| 密碼打錯或已被輪替 | 請管理者重新輪替一組 |
| 節點在 console 上被停用 | 請管理者重新啟用 |
| client id 與 pinning 不符 | 檢查是否為 `zqs:<edge_node_id>` |

### 11.6 與「上線宣告」的關係

§5.2 的 `Properties/…` 是**宣告**，這組帳密是**身分**。兩者刻意分開：帳密證明「你是
這個已註冊的節點」，宣告只是「我說我是什麼、我能做什麼」。宣告不會提升權限。

---

## 12. 表後（behind-the-meter）儲能的內建 metric key

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

正負號的約定很重要：energy aggregator 是依號誌來區分輸入與輸出、充電與放電。若硬體
採用相反的約定，請在該能源資產上設定 **Invert sign**，不要去改韌體。

其他 key 也一律接受——可透過 `POST /api/metrics` 定義，讓 console 知道它的單位與
標籤，或就讓它以未標記的形式通過。

---

## 13. 驗收工具

出貨前請跑一次一致性測試工具。它會用真的 MQTT 封包解析你的連線，逐項檢查本文提到的
每一條規則，並且用中文說明哪裡不對、怎麼改：

```bash
# 先確認工具本身是對的
python scripts/run_device_test.py self-test

# 再測你的設備
python scripts/run_device_test.py device --device ZQS-BESS-0001
```

檢查的項目包含 clean session、遺言的 topic/QoS/retain/bdSeq、NBIRTH 的 seq 是否為
0、bdSeq 是否與遺言一致、是否宣告 `Node Control/Rebirth`、BIRTH 有沒有指派 alias、
seq 是否連續、命令有沒有回覆、以及重生要求有沒有被理會。

細節見 [device-test-harness.md](device-test-harness.md)。

---

## 14. 沒有硬體時的快速驗證

```bash
python manage.py simulate_device --device ZQS-BESS-0001 --profile battery --interval 5
```

一個行程服務整個網關（這才是 Sparkplug 的正常用法）：

```bash
python manage.py simulate_device \
    --device ZQS-BESS-0001=battery \
    --device ZQS-METER-0001=meter \
    --device ZQS-PV-0001=pv --interval 5
```

這會發布與上述完全相同的訊息，因此也可以當作 wire format 的參考實作。
