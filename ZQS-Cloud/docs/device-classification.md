# 設備分類與能源角色（設計提案）

狀態：**已拍板，部分實作**。20 個待拍板項全部採用本文的建議。

- **已實作**：能力模型與命令檢查、`include_in_balance` 與重複計算修正、
  `generator` 角色、計數器差值與 reset 處理、設備宣告與信任邊界。
- **僅設計**：運轉 session、多來源成本模型、分項成本表。

**後續政策變更（已實作）：設備的類別永遠不會被修改。** 硬體真的變了就建立
接替設備、把舊的退役。這推翻了本文 §3.5–3.7 原本設計的「隨時可接受宣告」流程
——採用宣告現在只在驗收階段可用一次，之後的分歧一律視為「硬體被換掉了」。
細節見 [system-logic.md](system-logic.md) §1.5、§4.4、§10、§11。

系統目前**實際的**行為規則見 [system-logic.md](system-logic.md)。

---

## 1. 現況

### 1.1 `Device` 沒有任何能力欄位

| 欄位 | 位置 | 現況 |
| --- | --- | --- |
| `DeviceType.category` | blueprint | 有 11 種：`battery`、`pcs`、`generation`、`meter`、`load`、`generator`、`ev_charger`、`controller`、`sensor`、`gateway`、`other` |
| `DeviceType.command_definitions` | blueprint | JSON 陣列，每個命令帶 `params` 的 JSON-schema 與 `min_role` |
| `Device` 上的能力欄位 | — | **完全沒有** |

`category` 目前**只有一處在讀**：`apps/devices/api.py:391` 把它放進設備詳情的
回應裡。沒有任何邏輯依它分支。也就是說它是純標示，不是可執行的分類。

另外 `Device.device_type` 是 nullable——設備可以完全沒有 blueprint，此時連
命令目錄都沒有。

### 1.2 `EnergyAsset.role` 是「量測綁定」，不是「設備分類」

`AssetRole` 六種：`grid_meter`、`load_meter`、`pv`、`battery`、`ev_charger`、
`generator`。實際被 `SiteAggregator.compute_interval()` 使用的方式：

```
grid_meter                → grid 積分   → grid_import_kwh / grid_export_kwh / peak
pv                        → pv 積分     → pv_kwh
battery                   → battery 積分 → charge / discharge / SOC
load_meter, ev_charger    → load 積分   → load_kwh
generator                 → 落入 else，被忽略
```

關鍵觀察三點：

1. **role 回答的是「這台設備的哪個 metric，供應能量平衡中的哪一條流」**，
   不是「這台設備是什麼」。`GRID_METER` 這個名字本身就說明了它是量測點。
2. **`generator` 角色目前會被 aggregator 直接跳過**（`else: continue`）——
   建了也不會進入任何統計。
3. `EnergyAsset` 上已經有 `power_metric` / `soc_metric` / `power_scale` /
   `invert_sign` 這些純量測綁定欄位，以及 `rated_power_kw` /
   `rated_energy_kwh` 這兩個銘牌欄位。

所以：**`EnergyAsset` 已經是量測綁定層，而設備能力層目前是空的。**

### 1.3 下行命令完全不檢查設備能力

`apps/devices/services.py` 的 `dispatch_command()` 依序檢查：

1. `device.is_enabled`
2. 命令名稱是否在 blueprint 的 `command_definitions` 裡
3. `min_role` 角色權限
4. `params` 對 JSON-schema 的驗證

**沒有任何一步問「這台設備能不能做這件事」。**

具體的漏洞：`bess-pcs` blueprint 的 `set_power_setpoint` 允許
`power_w` 在 ±5,000,000 之間。負值就是充電。一台只能放電的機器只要掛在這個
blueprint 底下，就能被下達充電指令，系統不會攔。

### 1.4 控制路徑目前是斷的

- `DispatchWindow` model 的 docstring 寫「The scheduler turns these into
  device commands」，但**沒有任何程式碼消費它**——只有 API 的建立、列出、
  刪除。`run_scheduler` 跑的是 `aggregate_energy` / `build_rollups` /
  `prune_telemetry`，與 dispatch 無關。
- `StoragePlan` 的 `max_charge_kw`、`min_soc_percent`、
  `backup_reserve_percent` 在 API 層有互相一致性的驗證，但**執行期沒有任何
  地方強制**。唯一讀它們的是 `generate_history`（示範資料產生器）。

換句話說，今天命令抵達設備的唯一途徑是有人呼叫
`POST /devices/{id}/commands`，而 `dispatch_command()` 是**唯一的關卡**。這
對設計是好消息：只要守住這一個函式就守住全部。

### 1.5 上線宣告：已經有了，只是還沒被當成宣告用

**`status` topic 就是現成的 birth message。** 協定 §3.3 的 payload 已經帶
`firmware`、`hardware`、`ip`、`rssi`、`location`，而且要求 retained 發布，
所以重新連線的伺服器一定看得到最後一次宣告。不需要新增 `$SYS`（那是 EMQX
內部的，設備不能寫）或另開 register topic。

`StatusProcessor`（`services/worker/processors.py:257`）已經把這些值寫進
`Device`：`firmware_version`、`hardware_version`、`ip_address`、`rssi`、
`latitude` / `longitude`。

**而且這裡已經有一個「設備宣告 vs 系統認定」的前例**：

```python
updates["location_source"] = "device"       # processors.py:315
```

`Device.location_source` 的 help_text 是 `device | manual | site`——設備自己
報的座標會被標記來源，跟人工設定的區分開。這正是要推廣到能力欄位的模式。

### 1.6 設備要連上來，得先有憑證

- EMQX 的 auth webhook（`apps/devices/emqx.py`）逐一驗證
  `DeviceCredential`，ACL webhook 再把設備限制在自己的 topic 子樹內。
- `_check_token()` 在 `EMQX_WEBHOOK_TOKEN` 為空時直接丟
  `AuthenticationError`——**fail closed**，未設定就是全部拒絕。
- `INGEST_AUTO_PROVISION`（預設 `False`）開啟後，`processors.py:78` 會在第一
  次 uplink 時自動建檔：`name = device_id`、`description = "Auto-provisioned
  on first uplink"`、沒有 site、沒有 blueprint。

所以威脅模型是明確的：**攻擊者必須先持有某台設備的 MQTT 憑證**，而且只能冒
充那一台。這不是「任何人都能宣告自己是充電設備」，但「一台被入侵的設備能改口
說自己是什麼」——後者才是要防的。

---

## 2. 概念釐清：四層，不是一層

| 層 | 問題 | 放哪 | 生命週期 | 可信？ |
| --- | --- | --- | --- | --- |
| 型號能力 | 這**型**機器能做什麼？ | `DeviceType`（blueprint） | 跟著產品型錄走，跨租戶共用 | 可信（人建的） |
| 個體能力 | 這**台**機器實際能做什麼？ | `Device` | 跟著這台硬體的接線與合約走 | 可信（人確認的） |
| 場域角色 | 它在**這個場域**的能源模型扮演什麼？ | `EnergyAsset` | 跟著這個案場的單線圖走 | 可信（人建的） |
| **設備宣告** | 它**自稱**是什麼？ | `DeviceDeclaration`（新） | 跟著韌體走，每次上線覆寫 | **不可信** |

**為什麼型號與個體要分開。** 同型號的兩台 PCS 可能被裝成不一樣：一台雙向
併網，另一台因為現場沒拉充電迴路而只能放電；同一款電池櫃在 A 廠做套利、在
B 廠依合約只做備援。型號能力是預設值，個體能力是覆寫。

**為什麼能力與角色要分開。** 能力是物理事實（能不能吸收電能），角色是這個
案場的建模選擇（要把它算進哪一條流）。同一台雙向 PCS，在有 PV 的場域是
`battery`，在只做削峰的場域還是 `battery`，但如果它被拿去當某條饋線的量測
點，它就變成量測來源而不是儲能資產。把兩者塞進同一個欄位，就會出現
「`generator` 到底是設備類型還是能源角色」這種答不出來的問題——而這正是現在
`AssetRole` 的狀態。

### 2.1 電錶為什麼不該當成參與平衡的資產

電錶**不生產也不消耗**能量，它只是報數。把它當成「一個會貢獻能量的資產」在
兩種情況下會重複計算：

1. **總表 + 分表都綁成 `grid_meter`**：兩者量的是同一條線，相加後
   `grid_import_kwh` 直接翻倍。
2. **電池的 PCS 自己回報功率，同時又有一顆電錶量那條分支**，兩者都綁成
   `battery`：充放電量翻倍，SOC 統計也會被污染。

現在的唯一約束是 `unique(site, device, role)`——它只擋「同一台設備在同一角色
出現兩次」，擋不掉「兩台不同設備綁同一個角色」。而後者對 PV 是**正確的**
（兩台逆變器本來就要相加，`_merge()` 的註解也是這麼寫的），對市電總表則是
**錯的**。

正確的心智模型：**每一條能量流，恰好要有一條量測路徑。** PV 與電池可以有多
個實體單元各自量測後相加；市電只有一個併接點，只能有一個主量測。分表應該存
在（可視性有價值），但不該進入平衡。

---

## 3. 建議的資料模型

### 3.1 choices 還是能力旗標？兩者並存

**結論：`category` 留著做呈現與預設值，另外加明確的能力布林值做強制。**

單一 enum 表達不了真實硬體的組合。列出必須涵蓋的情境就看得出這是一個矩陣：

| 情境 | 可充 | 可放 | 可逆送市電 | 可被控制 | 量測用途 |
| --- | --- | --- | --- | --- | --- |
| 雙向 PCS／儲能電池 | ✓ | ✓ | ✓ | ✓ | |
| 備援電源（UPS） | ✓ | ✓ | ✗ | ✓ | |
| 備援電源（柴發） | ✗ | ✓ | ✗ | ✓ | |
| PV 逆變器 | ✗ | ✓（發電） | ✓ | 部分（可限電） | |
| 純電錶 | ✗ | ✗ | ✗ | ✗ | ✓ |
| 負載（不受控） | ✗ | ✗ | ✗ | ✗ | |

純旗標的問題是 UI 難選、驗證難寫；純 enum 的問題是組合爆炸。並存的分工：

- `category`（已存在）：決定圖示、預設能力、UI 分組
- 能力布林值：`dispatch_command()` 真正據以放行或拒絕的東西

**建議欄位**（`DeviceType` 上為預設值，`Device` 上為 `null = 繼承 blueprint`
的覆寫）：

```
can_charge          能在命令下吸收電能
can_discharge       能在命令下輸出電能
can_export          允許把電送回市電側
is_dispatchable     接受任何控制命令（電錶為 False）
```

`is_metering_only` **不另外開欄位**，但也**不能用能力推導**——見下。

> **修正（因補充需求而發現）：** 原本這裡寫的是用
> `not is_dispatchable and not can_charge and not can_discharge` 推導
> `is_metering_only`。加入「用電設備」這一類之後這個推導就壞了：一盞不可控的
> 照明四個旗標全是 `False`，會被推導成「純量測」，但它其實是**負載**。
> 正確的判斷是 `category == meter`，能力旗標回答的是「能不能被指揮」，不是
> 「是什麼」。這正是 §2 說「能力與類別是兩個軸」的實例。

### 3.2 備援電源的特殊需求

拆成兩件不同的事，放不同層：

| 需求 | 本質 | 建議放哪 |
| --- | --- | --- |
| 柴發不能充電 | 物理能力 | `Device.can_charge = False` |
| UPS 不可逆送 | 物理／法規限制 | `Device.can_export = False` |
| 保留 SOC 給停電用 | 運轉策略 | 已存在的 `StoragePlan.backup_reserve_percent`，但需要**per-asset 覆寫** |
| 只在市電中斷時動作 | 調度政策 | **新欄位 `EnergyAsset.availability`** |

`availability` 建議三值：`always`（隨時可調度）、`outage_only`（僅停電時）、
`manual`（只接受人工命令，排程器不碰）。

放在 `EnergyAsset` 而不是 `StoragePlan` 的理由：`StoragePlan` 是
`OneToOne(site)`。一個場域若有兩組電池——一組做套利、一組做備援——plan 層級
的欄位根本分不開它們。

### 3.3 功率上限與 SOC 界線放哪

專案現在**已經有一個合理的切分**，建議沿用並補齊：

| 性質 | 放哪 | 現況 |
| --- | --- | --- |
| 銘牌（硬體極限） | `EnergyAsset.rated_power_kw` / `rated_energy_kwh` | 已存在 |
| 運轉包絡（我們選擇怎麼用） | `StoragePlan.max_charge_kw` / `min_soc_percent` / `max_soc_percent` / `backup_reserve_percent` | 已存在，但只有驗證、沒有強制 |
| 單一資產的覆寫 | `EnergyAsset` 上的同名 nullable 欄位 | **待新增** |

生效值取三者最嚴：

```
effective_max_charge_kw = min(銘牌, plan 設定, asset 覆寫)  # 忽略 None
```

原則：**銘牌是事實，包絡是決策，決策不得超過事實。**

### 3.4 電錶的處理

- 電錶維持能建成 `EnergyAsset`（它就是量測綁定），但：
- 新增 `EnergyAsset.include_in_balance`（預設 `True`）。分表建成 `False`，
  於是它在頁面上看得到、可以畫圖，但不會被 `compute_interval()` 加總。
- 新增驗證：一個場域最多只能有一個 `include_in_balance=True` 的
  `grid_meter` 角色資產。PV / battery / ev_charger 不設此限（多台實體單元
  相加是正確的）。
- UI 上把這一頁的字樣從「資產」改成「量測綁定」，讓語意自己說話。

### 3.5 宣告值與認可值：分成兩組，控制只看認可值

設備上報的能力是**不可信輸入**。它決定的是「要不要放行一個會讓 50 kW 電力
反向流動的命令」，所以不能讓 payload 直接寫進拿來做決策的欄位。

**建議：不要在 `Device` 上加 `declared_can_charge` 這種平行欄位，而是另開一個
model。**

```
DeviceDeclaration            OneToOne(Device)
  payload            JSON    設備原封不動送來的 attributes
  schema_version     int
  received_at        datetime
  state              choices  pending | accepted | rejected | superseded
  reviewed_by        FK(User, null)
  reviewed_at        datetime null
  diff_summary       JSON     與目前認可值的差異，供 UI 直接顯示
```

分成獨立 model 而不是加前綴欄位，理由有三，第二點最重要：

1. 宣告是一份**會隨 `schema_version` 演進的文件**，塞成欄位每次都要 migration。
2. **它讓信任邊界在程式碼裡看得見。** `dispatch_command()` 拿到的是
   `Device`，而 `Device` 上根本沒有 `declared_*` 欄位——想誤用都沒得誤用。
   平行欄位則只差一個底線，`device.declared_can_charge` 和
   `device.can_charge` 在 code review 裡幾乎分不出來。
3. 審核歷程（誰在什麼時候接受了哪一版）自然有地方放。

對應地，`Device` 沿用 `location_source` 的模式加一個來源欄位：

```
Device.capability_source   choices  blueprint | manual | device
```

只有當管理者**明確接受**某次宣告時，才會寫入 `Device.can_charge` 等欄位並把
來源標成 `device`。設備自己永遠改不動這四個欄位。

### 3.6 新設備第一次上線的流程

建議**維持「預先建檔」為預設**（也就是現在 `INGEST_AUTO_PROVISION=0` 的行
為），但把 auto-provision 這條路做成**隔離區**而不是直接信任：

```
Device.commissioning_state   choices  pending | confirmed | rejected
```

| 情境 | 結果 |
| --- | --- |
| 後台預先建檔，設備上線並宣告 | `confirmed`；宣告存起來、比對、有差異就標示 |
| `AUTO_PROVISION=1`，未知設備上線 | 建檔為 `pending`，四個能力全部 `False`、`is_dispatchable=False` |
| `AUTO_PROVISION=0`，未知設備上線 | 維持現行：訊息丟棄，計入 `dropped.unknown_device` |

`pending` 的設備**照常收 telemetry**——操作者需要看到數據才能判斷這是什麼東
西——但**拒絕所有調度類命令**。這裡刻意不用既有的 `is_enabled=False`，因為那
個旗標的語意是「ingest 管線完全忽略它」，會讓操作者連判斷的依據都沒有。

**有人偽造宣告時會發生什麼：**

1. 攻擊者需要先取得該設備的 MQTT 憑證（見 §1.6，fail closed）。
2. 他讓設備宣告 `"can_charge": true`。
3. 宣告寫進 `DeviceDeclaration`，`state=pending`。
4. `Device.can_charge` **不變**。任何充電命令仍然被 `dispatch_command()` 以
   `capability_not_supported` 擋下。
5. 操作者在設備頁看到一個「宣告與認可值不符」的標示，以及 diff。

最壞情況是**一個誤導操作者的提示**，不是一個可執行的能力。剩下的風險就變成
社交工程——操作者被騙去按「接受」——所以接受這個動作必須是 ADMIN、必須進
audit log、而且 UI 要把差異講清楚（見 §3.7）。

要注意的組合是 `INGEST_AUTO_PROVISION=1`：它讓持有任一組有效憑證的人能大量
建立 `pending` 設備刷版面。建議文件上標明這個旗標只適合現場調試期間開啟。

### 3.7 宣告值與認可值不一致時

觸發時機：每次收到 `status` 的 `attributes` 就與目前認可值比對。

| 動作 | 放哪 | 理由 |
| --- | --- | --- |
| 記錄「設備報了新宣告」 | `DeviceEvent`（level `notice`，code `declaration.changed`） | `DeviceEvent` 的定義就是「設備自己回報的紀錄」，這是設備發起的事件 |
| 記錄「操作者接受／拒絕了宣告」 | `apps/audit`，新增 `DEVICE_DECLARATION_ACCEPTED` / `DEVICE_DECLARATION_REJECTED` | `AuditLog` 的定義是「操作者做了什麼」，接受是人的決定 |
| 通知 | 設備列表與詳情頁的徽章，加上一個「有待確認宣告」的篩選 | |

**刻意不做的**：不要因為宣告變動就自動觸發 `Alert`。`apps/alerts` 是量測值
門檻引擎，把設定漂移塞進去會污染告警語意，也會讓維運人員在韌體更新後被洗版。

**不要自動採用新值**，即使差異看起來無害。韌體更新後設備改口說額定從 50 kW
變成 60 kW，可能是型號真的換了、可能是韌體 bug、也可能是有人動了手腳。三種
情況的正確反應都不是「靜靜地改掉限制值」。

例外可以考慮：`firmware`、`hardware`、`ip`、`rssi` 這類**純敘述性、不影響控制
決策**的欄位維持現行的自動更新（它們現在就是這樣運作的），只有能力與額定值走
審核流程。這條界線就是「這個值會不會被 `dispatch_command()` 讀到」。

---

### 3.8 用電設備（load）

`DeviceCategory` 目前沒有 `load`。建議新增一個值 `load`（「用電設備」）。

**四個旗標怎麼填：**

| 情境 | can_charge | can_discharge | can_export | is_dispatchable |
| --- | --- | --- | --- | --- |
| 純被動負載（照明、插座迴路） | ✗ | ✗ | ✗ | **✗** |
| 可控負載（可遠端啟停的冰水機） | ✗ | ✗ | ✗ | **✓** |

**不需要為「可控負載」新增旗標**——`is_dispatchable` 的定義就是「接受控制
命令」，這正是可控與被動的差別。至於**能下哪些命令**，答案已經在
blueprint 的 `command_definitions` 裡（例如 `set_output_enabled`）；能力旗標
只負責「能不能」，命令目錄負責「能做什麼」。

唯一值得討論的是需量反應要不要專屬旗標 `can_shed`（可卸載）。建議**先不加**：
在沒有自動卸載引擎之前它只是一個沒人讀的欄位，等 dispatch 引擎真要做 DR 再
決定。（列為決策點 #13。）

### 3.9 個別用電設備與 `role=load` 的重複計算

**現況**：`compute_interval()` 把 `load_meter` 與 `ev_charger` 兩個角色**無條件
merge 成同一個 `load_metered`**；只有在完全沒有 load 角色資產時，才用節點平衡
反推 `load_kwh`。

所以「一個總負載表 + 三台個別機器都建成 `load_meter`」會直接把負載算成四份。
這比市電總表的情況更容易踩到——「我想看每台機器用多少電」是非常自然的需求。

**建議規則，一句話：`include_in_balance=True` 的 load 資產，加起來必須恰好
涵蓋場域負載一次。**

實務上只有兩種合法組態：

| 組態 | 設定 |
| --- | --- |
| 有總負載表 | 總表 `True`，所有個別設備 `False` |
| 沒有總表，逐饋線量測 | 所有饋線表 `True`（相加剛好是全部），設備層級的再掛 `False` |

個別用電設備照樣建成 `EnergyAsset`（它就是量測綁定）——有圖表、有耗能統計、
有運轉 session——只是**不進 `load_kwh`**。

配套：

- `ev_charger` 角色也要吃 `include_in_balance`。總表已經含充電樁時，現在的
  無條件併入就是重複計算。
- 一個場域出現**兩個以上** `include_in_balance=True` 的 load 資產時，UI 顯示
  提示「請確認這些量測互不重疊」。**不硬擋**——多饋線加總是合法的。
- 市電總表則相反，硬擋（§3.4），因為併接點物理上只有一個。

### 3.10 個別設備耗能：概念已經有了，只是線沒接上

調查結果比預期好：**「瞬時 vs 累計」的區分已經存在於 `Metric` 上**。

```python
class MetricKind(models.TextChoices):
    GAUGE = "gauge"        # 瞬時值
    COUNTER = "counter"    # 累計計數器
    STATE = "state"

class Aggregation(models.TextChoices):
    AVG / SUM / MIN / MAX / LAST / COUNTER   # COUNTER = "Counter delta"
```

`bootstrap` 的內建目錄也已經把 `grid_import_energy_kwh`、`pv_energy_kwh`、
**`load_energy_kwh`（累計用電量）** 全部標成 `MetricKind.COUNTER` +
`Aggregation.COUNTER`。

**所以不建議新增 `metric_kind` 概念——它已經在了。** 缺的是兩條沒接上的線：

| 缺口 | 現況 |
| --- | --- |
| `Rollup.first_value` / `last_value` | 欄位在 model 上定義了，但 `build_rollups()` 的 `update_fields` 裡沒有它們——**從來沒被寫入過** |
| `EnergyAsset.energy_import_metric` / `energy_export_metric` / `energy_scale` | 欄位定義了、`seed_demo` 也填了，但 `SiteAggregator` **從來不讀**，永遠走功率積分 |

#### 建議做法

新增一個共用函式（建議放 `apps/telemetry/energy.py`），依 metric 的 `kind`
選策略：

```
energy_kwh(device, metric_key, start, end):
    GAUGE   → 對功率做步進積分
    COUNTER → last - first（差值），並處理歸零與翻轉
```

**優先序：只要該資產同時有 COUNTER metric，就用 COUNTER。** 差值是設備自己
累計的，沒有取樣誤差；積分永遠是近似。

#### 查詢時算還是預存？

**建議：不新增表，直接用既有的 15 分鐘 `Rollup`。**

對 GAUGE：`kWh ≈ Σ(avg_value × interval_seconds / 3600)`。`Rollup` 已經有
`avg_value`、已經有 `(device, metric_key, interval_seconds, -bucket_start)`
的索引，`build_rollups` 也已經在排程裡每 5 分鐘跑。個別設備耗能因此是**一個
查詢，零張新表**。

對 COUNTER：需要先把 `first_value` / `last_value` 補進 `build_rollups()`，
然後 `delta = last - first`。這是三行改動，欄位早就在。

只有在「要跨整年、且要求高精度」時才值得專用的能量 rollup 表。建議先不做。

#### 積分誤差

`integrate_power()` 用的是**前值保持（zero-order hold）**，不是梯形法——
文件裡要寫清楚，免得有人以為是後者。對「回報間隔遠小於變化尺度」的訊號誤差
很小；對馬達啟停這種突變負載會有系統性偏差，方向取決於變化是上升還是下降。

三個既有機制就能控制它，不必改程式：

1. **`Integral.coverage`（已存在，0..1）**：低於門檻（建議 0.8）在 UI 標示
   「資料不完整」，不要把它當成確定的數字。
2. **recording policy 的 `max_interval_seconds`（心跳，預設 3600）決定誤差
   上界**。要做耗能統計的負載，建議把心跳調到 300 秒以內——這是既有的
   `RecordingRule` 設定，改資料就好。
3. **有 COUNTER 就用 COUNTER。**

#### 累計值歸零與翻轉

偵測條件很單純：`last < first`（計數器單調遞增，遞減必有事）。但**成因分不
出來**：換表歸零、32 位元溢位、韌體重啟重置，三者的正確處理不同。

建議：

- `first - last` 小於容差 → 視為雜訊，`delta = 0`
- 否則標記 `counter_reset`，該桶的 delta 記為 **`null`（未知）**，
  **不是 0 也不是負數**——把「不知道」誠實記成不知道，總比記成 0 讓月報悄悄
  短少一段好。同時發一筆 `DeviceEvent`（level `warning`、code
  `counter.reset`）。
- **不要自己猜 wrap-around 的模數。** 除非知道計數器上限，否則無法區分翻轉
  與換表。建議在 `Metric` 上加一個 nullable 的 `counter_max`：有值才做
  `delta = counter_max - first + last`，沒值就走上面的 `null` 路徑。
- 這也是 §5 設備宣告能派上用場的地方：`attributes.ratings` 可以帶
  `counter_max`，但一樣走審核流程，不自動採用。

### 3.11 運轉 session：最後一次充電／放電／運轉

#### 資料模型：獨立 model + `Device` 上的少量快取欄位

使用者的直覺是對的，**兩者都要**，但快取欄位要克制。

```
DeviceOperatingSession
  device          FK(Device)
  organization    FK          # 同 TelemetrySample 的做法，去正規化避免 join
  kind            choices     charge | discharge | running
  started_at      datetime    index
  ended_at        datetime    null = 進行中
  duration_s      int         null，關閉時填（冗餘，但讓「平均時長」是一個查詢）
  energy_kwh      float
  peak_kw         float
  avg_kw          float
  start_soc_percent / end_soc_percent   float null
  end_reason      choices     threshold | offline | recomputed
  unique(device, kind, started_at)
```

`Device` 上**只加三個 datetime**：

```
last_charge_at / last_discharge_at / last_running_at
```

不加 `last_charge_duration_s`、`last_charge_energy_kwh` 等等。取捨：

- 三個 datetime 可以**索引、排序、篩選**——「找出 30 天沒放電的電池」是一個
  `WHERE last_discharge_at < ...`，這是快取欄位真正的價值。
- 時長、能量這些細節去 session 表撈就好，列表頁不需要。多加六個欄位換來的
  只是省一次 join，卻多六個要維持同步的冗餘值。
- 也不建議用 `Device.last_sessions = JSONField`：JSON 無法排序也無法篩選，
  上面那個查詢就寫不出來了。

#### 判定邏輯：門檻 + 遲滯 + 最短時長

參數建議放在 **`EnergyAsset`** 上（它已經負責 `power_metric`、`power_scale`、
`invert_sign`，也就是「這台設備的功率讀數怎麼解釋」——session 判定需要的正是
這些）：

| 參數 | 預設 | 作用 |
| --- | --- | --- |
| `session_enter_kw` | `rated_power_kw × 2%`，下限 0.5 kW | 超過才算開始 |
| `session_exit_kw` | `session_enter_kw × 0.5` | 低於才算結束 |
| `session_min_duration_s` | 60 | 短於此的 session 直接丟棄 |
| `session_gap_s` | 300 | 超過這麼久沒資料就收尾 |
| `session_tracking_enabled` | 依 category（battery 為 `True`，load 為 `False`） | 整個關掉 |

**遲滯**：`enter > exit`，功率在兩者之間抖動不會反覆開關 session。這是避免
假 session 的主要機制——單一門檻遇到在門檻附近震盪的負載會產生成千上萬筆。

**最短時長**：session 關閉時若 `duration_s < session_min_duration_s` 就**不
寫入**。馬達啟動瞬間的突波因此不會變成一筆 1 秒的「放電」。

**資料中斷**：距離最後一個樣本超過 `session_gap_s` 仍無新資料 → 用**最後一個
樣本的時間**收尾，`end_reason = "offline"`。能量只計到最後一個樣本為止——
不要往中斷區間外推，我們不知道那段時間發生了什麼。

**充電 vs 放電**：對 battery，正規化（`power_scale` + `invert_sign`）之後
`power < -enter_kw` 是充電、`power > +enter_kw` 是放電。這也是為什麼參數要跟
著 `EnergyAsset` 走——符號約定在那裡。

#### 「用電」的 session 要改成「運轉／停機」

使用者的觀察是對的：一台一直在耗電的負載，「用電 session」永遠是 open，沒有
資訊量。

建議：對 `category=load`，kind 用 **`running`**，以門檻功率定義「運轉中」，
預設門檻取額定的 **5%**（待機功耗通常落在 1–3%，5% 能把待機和運轉分開）。

- 對間歇運轉的設備（冰水機、空壓機）這很有用：一天啟停幾次、每次多久、耗多少。
- 對 24 小時不間斷的設備（機房空調），會產生一個永遠 open 的 session——這是
  **正確且有用的**（「已連續運轉 37 天」）。不要強制切斷它，但列表頁對超過
  N 天的 open session 給個標示。
- 對完全沒有意義的對象（照明總迴路），用 `session_tracking_enabled=False`
  關掉，只看每日 kWh。所以預設值 load = `False`，要的人自己開。

#### 誰來算：建議排程回算，不要在 worker 裡放狀態機

| 方案 | 優點 | 問題 |
| --- | --- | --- |
| worker 即時判定 | 「最後一次放電」秒級即時 | 亂序與遲到訊息會污染狀態機；worker 重啟要復原狀態；熱路徑變重 |
| **排程回算（建議）** | 亂序、遲到、重啟三個問題一次消失，每次都從資料重算 | 延遲最多一個排程週期 |

**建議走排程回算**，理由是它和既有的 `aggregate_energy` **完全對稱**——那個
命令的預設就是 `--hours 2`，註解寫明「刻意重疊，讓遲到的資料修正它所屬的
區間」。session 走同一條路，維運只需要一套心智模型。

具體：在 `run_scheduler` 的迴圈裡加一個 `rebuild_sessions --hours 2`，
每 5 分鐘跑一次。代價是「最後一次充電」最多延遲 5 分鐘——而這個數字不需要
秒級即時。

**冪等性**是回算的前提：重算前先刪掉視窗內 `started_at` 落在範圍內的 session，
再重建。要注意跨越視窗左邊界的 session——回算範圍要往前延伸到「最後一筆已關閉
session 之後」，否則會把一個進行中的長 session 切成兩半。

順帶一提，**目前無法用查詢找出「哪些設備有遲到資料」**：`TelemetrySample`
只有 `ts`，沒有 `received_at`。所以固定 lookback 是唯一可行的做法，另外提供
`manage.py rebuild_sessions --device X --since ...` 與對應的 API 端點供手動
修補（與既有的 `POST /ems/sites/{id}/rebuild-intervals` 對稱）。

#### 與 `EnergyInterval` 的關係：兩種粒度，不要混

| | `EnergyInterval` | `DeviceOperatingSession` |
| --- | --- | --- |
| 對象 | **Site** | **Device** |
| 邊界 | 固定網格，15 分鐘對齊 | 事件驅動，由設備行為決定 |
| 是否恆存在 | 是，沒事發生也有一列 | 否，只有真的動作才有 |
| 回答什麼 | 結算、電價、需量、月報 | 這台機器動了幾次、多久、耗多少 |

**兩者不該互相推導。** 同一段時間會同時出現在兩邊，但問的是不同問題。特別
是：session 的 `energy_kwh` 要從 raw sample 或 `Rollup` 算，**不要**去切
`EnergyInterval`——粒度對不上，而且 `EnergyInterval` 是場域層級，根本沒有
單一設備的資訊。

### 3.12 可擴充的成本模型

現況：`compute_interval()` 只認得一種成本——市電。

```python
price = resolve_price(self.plan.tariff if self.plan else None, start)
energy_cost = grid_import * price.import_price
export_revenue = grid_export * price.export_price
```

`apps/ems/tariffs.py` 的 `Price` dataclass（`period_name` / `import_price` /
`export_price` / `currency`）就是目前唯一的成本抽象。電池放電、柴發輸出目前
在成本上**完全不計價**。

#### 抽象結構：註冊表，不是 if/elif

`services/bus/factory.py` 的寫法（`if backend == "redis": ... elif ...`）對
**由運維二選一的後端**很合適：選項少、由設定檔決定、新增後端是核心團隊的事。

成本模型不一樣：目標明確是「之後新增設備類型時不必改動核心結算邏輯」。所以
建議往上一階，用**註冊表 + 裝飾器**：

```
apps/ems/costs/
  base.py       CostModel 介面、CostContext、CostResult、registry
  grid.py       @register("grid_tariff")
  battery.py    @register("battery_cycle")
  diesel.py     @register("diesel_fuel")
  __init__.py   import 各模組以觸發註冊
```

介面刻意窄：

```
CostContext   # 輸入，由 aggregator 組好遞進來
  start, end, interval_seconds
  energy_kwh          這個區間該來源輸出/消耗了多少
  avg_kw, peak_kw
  asset               EnergyAsset（帶參數）
  plan                StoragePlan | None
  price_at(moment)    市電價查詢，讓電池模型能算加權平均充電成本
  soc_start, soc_end

CostResult    # 輸出
  amount              金額（正 = 成本，負 = 收益）
  currency
  unit_cost_per_kwh   單位成本，報表用
  breakdown           {"fuel": 1200.0, "maintenance": 150.0} 之類的分項
  basis               "measured" | "estimated" | "unknown"
```

沿用 `build_bus()` 的錯誤處理慣例：未知的 key 丟
`UnknownCostModel`（比照 `BusError`），不要靜默回 0——成本靜默歸零是最難發現
的錯誤之一。

**由誰決定套用哪個模型：`EnergyAsset.cost_model`（字串 key，nullable）。**
不要用 `category → model` 的硬對應：兩台柴發可能一台用實測油耗曲線、一台用
簡化的固定 L/kWh，那是同一個 category 不同模型。`null` 時才回退到 category
的預設對應。

#### 參數放哪：沿用四層原則

原則不變——**物理事實跟著硬體，商業條件跟著場域**。

| 參數 | 放哪 | 理由 |
| --- | --- | --- |
| 柴發油耗曲線（L/kWh 對負載率） | `DeviceType` 預設，`Device` 可覆寫 | 引擎的物理特性，屬於型號；個體實測值會偏離，所以允許覆寫 |
| 電池往返效率 | `DeviceType` 預設 → `Device` 覆寫 → 已存在的 `StoragePlan.round_trip_efficiency` | 同上；plan 上那個現有欄位語意是「場域層級的設定值」，保留作為最後回退 |
| 電池循環衰退成本（元/kWh 吞吐） | **`EnergyAsset`** | 這是「電池總價 ÷ 保證循環數」算出來的**商業數字**，跟採購合約走，不是型號屬性 |
| 油價 | **`EnergyAsset`**（見下方時間性問題） | 商業條件，隨場域與時間變 |
| 維護成本（元/運轉小時） | **`EnergyAsset`** | 維護合約，商業條件 |
| 市電電價 | 已存在的 `Tariff` + `StoragePlan.tariff` | 不動 |

**油價的時間性是個真問題。** 今天的油價不能用來重算三個月前的成本，而
`Tariff.periods` 已經解決過一次同樣的問題。兩個選項：

- **短期**：`EnergyAsset.fuel_price_per_litre` 單一值，明確記載「重算歷史區間
  會套用當前油價」的限制。
- **正確**：另開一個帶生效期間的 `CostParameterSet`（asset、生效起訖、JSON
  參數），`CostContext` 依 `start` 取用當時的值。

建議短期先做前者、把限制寫在 UI 上，等真的要出月報再做後者。列為決策點 #14。

#### 設備宣告怎麼影響成本模型：只能「建議」

`attributes` 可以帶 `cost_model_hint`（例如 `"diesel_fuel"`）與
`ratings.fuel_consumption_l_per_kwh`，但——與 §3.5、§3.6 完全一致——

- 宣告只寫進 `DeviceDeclaration`，`state=pending`
- **`EnergyAsset.cost_model` 與所有成本參數只能由 ADMIN 經 API 設定**
- 結算邏輯讀的永遠是 `EnergyAsset` 上的欄位，**絕不查 `DeviceDeclaration`**

理由在這裡比能力旗標更直白：成本模型直接決定帳單數字與節費報表。一台被入侵
的設備若能自己宣告「我的油耗是 0.01 L/kWh」，報表就會顯示柴發比市電便宜十倍，
而運維人員可能據此做出錯誤的調度決策。§4.1 那個釘住信任邊界的測試，建議同時
涵蓋成本模型：**寫入一份宣告 `cost_model_hint`，斷言結算結果不變。**

#### 與 `EnergyInterval` 的整合：新開分項表，總計欄位保留

三個選項：

| 方案 | 評價 |
| --- | --- |
| 每個來源加一組欄位（`diesel_cost`、`battery_cost`…） | **否**。每新增一種設備類型就要 migration，正好違反「不必改動核心」的目標 |
| `EnergyInterval.cost_breakdown = JSONField` | 可擴充，但無法用 SQL 聚合——「這個月柴發花了多少」會變成全表掃描後在 Python 加總 |
| **新開 `EnergyIntervalCost`（建議）** | 正規化、可擴充、可聚合 |

```
EnergyIntervalCost
  interval        FK(EnergyInterval, related_name="costs")
  source          choices  grid | battery | generator | ev | other
  cost_model      str      實際套用的 key，方便日後追查
  energy_kwh      float
  amount          float    正 = 成本，負 = 收益
  currency        str
  unit_cost       float
  breakdown       JSON     {"fuel": ..., "maintenance": ...}
  basis           str      measured | estimated | unknown
  unique(interval, source)
```

`EnergyInterval.energy_cost` / `export_revenue` / `estimated_savings`
**保留為總計**，語意不變——既有的儀表板、`_totals()`、跨站 roll-up 全都不用
改。分項是新增的細節層。

**這一併釐清了決策點 #3。** 之前把「柴發要不要獨立於 `battery_*` 統計」列為
待拍板，理由是成本模型不同會讓節費失真。有了分項成本表，成本問題自己解決了
——但**能量欄位仍然要分開**，理由換成另一個：`round_trip_efficiency` 算的是
`discharge / charge`，柴發只放不充，把它的輸出併進 `battery_discharge_kwh`
會讓往返效率算出大於 1 的荒謬值。

所以修正後的建議是：`EnergyInterval` **新增一個 `generator_kwh` 欄位**（節點
平衡本來就需要它：`load = grid + pv + battery + generator`），成本則走分項表。

#### 幣別與單位

> **已實作。** `Organization.reporting_currency`（預設 `TWD`）、
> `currency_mismatch` 的儲存時檢查、以及沒有電價方案的場域退回組織幣別，
> 都已經在程式裡了。見 system-logic.md §6.5 與 `tests/test_reporting_currency.py`。

原則：**一個場域只能有一種報表幣別，而且這件事要在設定時擋，不是在報表時
發現。**

- 幣別歸屬提升到 `Organization`（或 `Site`）的 `reporting_currency`，而不是
  散落在每個 `Tariff` 上。
- 每個成本模型產出的 `CostResult.currency` 必須等於報表幣別，否則在**儲存
  設定時**就拒絕（`currency_mismatch`），不要等到月報才發現加了一堆不同幣別。
- §「跨站彙總」那條「幣別不一致就回空字串」的規則保留為**最後防線**，但正常
  情況下不該被觸發。
- **匯率換算明確不在範圍內。** 匯率有時間性、有買賣價差、有會計政策，那是另
  一個系統的職責。

單位同理：模型內部一律 kWh、kW、以及該幣別的元。油耗以 L/kWh 表示、油價以
元/L 表示，兩者相乘得元/kWh——單位在 `CostModel` 的 docstring 裡寫死，不要讓
呼叫端猜。

#### 節費基準線：允許負值，並且承認「停電時沒有基準線」

現行算法：

```
baseline = 同樣的負載與 PV，但沒有電池
estimated_savings = baseline_cost - actual_cost
```

多來源之下有兩個問題：

**問題一：柴發可能比市電貴。** 那 `estimated_savings` 就是負的——**算術是對
的，用詞是錯的**。建議：

- 欄位名 `estimated_savings` 保留（相容性），但 UI 文案改成「相對基準線的
  成本差異」，負值照實顯示（紅色），**絕對不要 clamp 到 0**。把成本增加藏起
  來，等於讓報表替一個錯誤的調度決策背書。
- 基準線改成可設定：`StoragePlan.savings_baseline` 三選一——
  `grid_only`（什麼都沒裝、全部買市電）、`no_storage`（現行：有 PV 沒電池）、
  `none`（不算）。多來源情境建議預設 `grid_only`，因為它回答的問題最清楚。

**問題二：停電期間沒有基準線可言。** 市電斷了的時候，柴發與電池的輸出**沒有
「改買市電」這個替代方案**——拿市電價當基準是在比較一件不存在的事。這種區間
的「節費」是虛構的數字。

建議：當某個區間內有 `availability=outage_only` 的資產產生了能量時，該區間的
`estimated_savings` 記為 **`null`（未知）而不是任何數字**，並在報表上標示
「停電期間，不計節費」。這和 §3.10 對 counter reset 的處理是同一個原則：
**不知道就記成不知道。**

（這需要 §決策點 #4 的停電判定。在停電偵測做出來之前，退而求其次的近似是
「該區間有 generator 輸出」，並在文件上標明這是近似。）

---

## 4. 控制安全：擋在哪一層

三層都要，但職責不同：

| 層 | 擋什麼 | 為什麼 |
| --- | --- | --- |
| API／schema | 形狀與範圍（`params` 的 JSON-schema） | 已經有了，便宜且立即 |
| **`dispatch_command()`** | **能力與策略** | **唯一關卡**——所有命令都經過這裡，包括未來的排程器 |
| 設備韌體 | 最後防線 | 協定文件 §4 第 2 點已經要求裝置自行驗證 |

建議在 `dispatch_command()` 現有的 blueprint 檢查之後、寫入 Command 之前，
插入一個 `_check_capability(device, name, params)`。它必須理解**命令的語意**，
而不只是名稱——因為 `set_power_setpoint` 帶負值就是充電。

### 建議的錯誤碼

沿用專案既有慣例（`device_disabled`、`unknown_command`、
`parameter_out_of_range`）：

| 代碼 | HTTP | 情境 |
| --- | --- | --- |
| `capability_not_supported` | 422 | 對不能充電的設備下充電命令 |
| `export_not_permitted` | 422 | 設定值會導致不可逆送的資產送電回市電 |
| `soc_reserve_protected` | 409 | 放電會侵蝕備援保留水位 |
| `asset_not_dispatchable` | 422 | 對電錶或 `availability=manual` 的資產下命令 |
| `device_unconfirmed` | 409 | 設備還在 `commissioning_state=pending`，尚未被確認 |

`details` 帶上 `{"capability": "can_charge", "device_id": ...}`，讓 console
能翻成使用者看得懂的訊息並停用對應按鈕。

### 4.1 檢查一律讀認可值

`_check_capability()` 只能讀 `Device` 上的四個能力欄位（必要時往上取
blueprint 預設值）。**它不得查詢 `DeviceDeclaration`。** 這條規則值得在函式
的 docstring 裡寫死，並且用一個測試釘住：

> 建一台 `can_charge=False` 的設備，寫入一份宣告 `can_charge=True`，
> 斷言充電命令仍然被拒。

這個測試是整個信任邊界的具體化——它會在有人「順手」把宣告值接進判斷式時失敗。

## 5. 協定擴充：設備怎麼宣告

### 5.1 用哪個 topic

**建議：擴充現有的 `status`，不要新增 topic。**

`spBv1.0/{group}/DBIRTH/{node}/{device}` 就是 birth message：連線後立刻發布、
retained、QoS 1，而且 LWT 就掛在同一個 topic 上。加一個可選的 `attributes`
物件即可。

| 方案 | 取捨 |
| --- | --- |
| **擴充 `status`**（建議） | 不用改 ACL、不用改 ingestor 訂閱清單、不用改 LabVIEW 的連線流程；retained 讓重連的伺服器一定拿得到 |
| 新開 `register` topic | 語意更乾淨，但要動 `UPLINK_SUFFIXES`、EMQX ACL 的 `_PUBLISHABLE`、協定文件與每一份韌體 |

`$SYS` 不可行——那是 EMQX 內部樹，設備沒有寫入權限。

**只在 birth message 帶 `attributes`**（也就是 `{"status":"online"}` 那一
則），一般的狀態變更不必重複。LWT 之後 retained 的內容會被 offline 訊息取
代，但那不影響——伺服器收到當下就已經存進資料庫了。

### 5.2 Payload schema

```json
{
  "status": "online",
  "ts": 1780000000000,
  "reason": "boot",
  "firmware": "2.1.4",
  "attributes": {
    "schema_version": 1,
    "category": "pcs",
    "blueprint": "bess-pcs",
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
      "max_charge_kw": 50.0,
      "max_discharge_kw": 50.0,
      "min_soc_percent": 10.0,
      "max_soc_percent": 90.0
    },
    "metrics": ["battery_soc", "battery_power_w", "battery_temperature_c"],
    "commands": ["set_power_limit", "set_mode", "emergency_stop"]
  }
}
```

| 欄位 | 型別 | 必要 | 說明 |
| --- | --- | --- | --- |
| `schema_version` | integer | 是 | 目前為 `1`。伺服器拒絕不認得的版本，並記為 `declaration.unsupported_version` |
| `category` | string | 是 | 對應 `DeviceType.category` 的九個值之一；不認得的值視為 `other` |
| `blueprint` | string | 否 | 建議對應的 blueprint `key`。**只是建議**，不會自動綁定 |
| `manufacturer` / `model` / `serial_number` | string ≤ 120 | 否 | 供操作者比對機器銘牌 |
| `capabilities.*` | boolean | 否 | 四個能力旗標，缺省視為未宣告（不是 `false`） |
| `ratings.rated_power_kw` | number > 0 | 否 | 銘牌功率 |
| `ratings.rated_energy_kwh` | number > 0 | 否 | 電池可用容量 |
| `ratings.max_charge_kw` / `max_discharge_kw` | number ≥ 0 | 否 | 韌體自己的限值 |
| `ratings.min_soc_percent` / `max_soc_percent` | number 0–100 | 否 | 韌體自己的 SOC 界線 |
| `metrics` | string 陣列 ≤ 128 | 否 | 這台會回報哪些 metric key，供 catalogue 比對缺漏 |
| `commands` | string 陣列 ≤ 64 | 否 | 這台支援哪些命令，供與 blueprint 的 `command_definitions` 比對 |

整個 `attributes` 為可選：不送的設備行為與現在完全相同。ingestor 的
`MAX_PAYLOAD_BYTES`（256 KB）綽綽有餘，但建議另外對 `attributes` 設一個 8 KB
的上限，避免有人拿 birth message 當儲存空間。

**LabVIEW 端的成本**：多組一個字串常數。這些值在編譯期就知道，不需要動態
計算——正好符合協定文件 §6 建議的「固定格式用字串串接」。

### 5.3 伺服器怎麼處理

在 `StatusProcessor` 現有流程之後追加一步：

1. 沒有 `attributes` → 什麼都不做（現行行為）。
2. `schema_version` 不認得 → 記一筆 `DeviceEvent`，忽略內容。
3. 與 `DeviceDeclaration.payload` 逐欄位比對：
   - 完全相同 → 只更新 `received_at`，不吵人。
   - 有差異 → 寫入新的 declaration（舊的標 `superseded`）、算出
     `diff_summary`、`state=pending`、發一筆 `DeviceEvent`。
4. **任何情況下都不動 `Device` 的能力欄位。**

第 3 點的「完全相同就不吵」很重要：設備每次重連都會發 birth message，若每次
都產生一筆待審核，這個機制一週內就會被操作者忽略。

---

## 6. 對現有資料與程式的影響

### Migration

全部是 nullable 或有預設值的 `AddField`，**不需要 data migration**：

| 對象 | 欄位 |
| --- | --- |
| `DeviceType` | `can_charge` / `can_discharge` / `can_export` / `is_dispatchable`（布林，有預設） |
| `Device` | 同名四個，`null=True` 代表繼承 blueprint |
| `EnergyAsset` | `include_in_balance`（預設 `True`）、`availability`（預設 `always`）、四個 nullable 的包絡覆寫欄位 |
| `Device` | `capability_source`（預設 `blueprint`）、`commissioning_state`（**既有資料一律 `confirmed`**） |
| `DeviceDeclaration` | 新 model，`CreateModel`，不影響既有資料 |
| `DeviceCategory` | 新增 `load` 值（改 choices，不需 data migration） |
| `Metric` | `counter_max`（nullable，只有宣告了上限的計數器才做 wrap 修正） |
| `EnergyAsset` | session 判定參數 5 個、`cost_model`、成本參數（油價、循環成本、維護費率） |
| `DeviceOperatingSession` | 新 model |
| `EnergyIntervalCost` | 新 model |
| `EnergyInterval` | `generator_kwh`（預設 0.0）；`estimated_savings` 改為 nullable 以表達「停電期間未知」 |
| `Device` | `last_charge_at` / `last_discharge_at` / `last_running_at`（皆 nullable） |
| `Organization` 或 `Site` | `reporting_currency` |

### 既有資料怎麼歸類

建議**不寫 data migration**，改由 `manage.py bootstrap --update-existing`
依 `category` 設定內建 blueprint 的能力預設值（該命令本來就是冪等、可重跑
的）：

| category | can_charge | can_discharge | can_export | is_dispatchable |
| --- | --- | --- | --- | --- |
| `battery` / `pcs` | ✓ | ✓ | ✓ | ✓ |
| `generation` | ✗ | ✓ | ✓ | ✓ |
| `ev_charger` | ✓ | ✗ | ✗ | ✓ |
| `meter` / `sensor` | ✗ | ✗ | ✗ | ✗ |
| `controller` / `gateway` / `other` | ✗ | ✗ | ✗ | ✓ |

`Device` 的四個欄位一律留 `null`（繼承）。使用者只需要為「和型號預設不同」的
個別設備去勾——例如那台只能放電的 PCS。

**沒有 blueprint 的設備**（`device_type=None`）沒有能力資訊。建議維持寬鬆
放行以免弄壞既有安裝，但在設備詳情頁明確顯示「未指定型號，未做能力檢查」。

### 會受影響的邏輯

- **`SiteAggregator.compute_interval()`**：一旦開始尊重
  `include_in_balance`，已經建了分表的場域數字會改變。需要在上線後對受影響
  的場域跑 `POST /ems/sites/{id}/rebuild-intervals`。
- **`generator` 角色**目前被忽略，若備援電源要進統計，得決定它算哪一條流
  （建議：放電時併入 `battery_discharge_kwh`，或新增獨立欄位——見第 6 節）。
- **`StatusProcessor`** 多一個分支。沒送 `attributes` 的設備完全不受影響，
  所以既有韌體不需要同步更新。
- **`AuditAction`** 要加兩個值。註解已寫明「stable action keys - never reword
  in place」，新增是安全的。
- **`build_rollups()`** 要開始寫入 `first_value` / `last_value`（欄位早就在
  model 上，只是從來沒被填過）。這是純新增，既有的 avg/min/max/sum 不變。
- **`compute_interval()`** 要改的地方：`ev_charger` 與 load 角色開始尊重
  `include_in_balance`、新增 `generator_kwh`、成本改走註冊表。**已經建了個別
  用電設備當 `load_meter` 的場域，數字會改變**（原本重複計算，修正後才對），
  需要跑 `rebuild-intervals`。
- **`EnergyInterval.estimated_savings` 改 nullable** 會影響前端：所有讀這個
  欄位的地方都要處理 `null`（顯示「停電期間不計」而非 0）。
- 其他統計不受影響，因為今天沒有任何程式讀能力欄位。

### 前端

| 頁面 | 改動 |
| --- | --- |
| `DevicesPage` | 能力徽章（可充／可放／量測）、blueprint 欄位 |
| `DeviceDetailPage` | 依能力停用命令按鈕，並顯示停用原因 |
| `StoragePage` | 每個資產的包絡與 `availability` 顯示 |
| 資產編輯器 | 新增 `include_in_balance`、`availability`、包絡覆寫 |
| `DeviceDetailPage` | 「設備宣告」區塊：diff、接受／拒絕按鈕（ADMIN）、來源標示 |
| `DevicesPage` | 「有待確認宣告」與「待驗收（pending）」的篩選與徽章 |
| `DeviceDetailPage` | 耗能區塊（日/月 kWh）、運轉 session 列表與「最後一次充/放/運轉」 |
| `StoragePage` | 分項成本（依來源）、負節費以紅色照實顯示、停電區間標示 |
| 資產編輯器 | `cost_model` 與其參數、session 判定門檻 |

---

## 7. 需要拍板的分歧點

| # | 問題 | 我的建議 | 理由 |
| --- | --- | --- | --- |
| 1 | 這一輪要不要一起做 dispatch 引擎？ | **不要**，只做資料模型與 `dispatch_command()` 的把關 | `DispatchWindow` 現在無人消費、`StoragePlan` 的限制也沒人強制。把「能力模型」和「自動調度」綁在一起做，範圍會膨脹到難以驗收。先把資料與關卡建好，調度引擎獨立一期 |
| 2 | 能力覆寫放 `Device` 還是只放 blueprint？ | **兩層，`Device` 為 nullable 覆寫** | 同型號不同接線是真實情況；只有 blueprint 會逼使用者為每種接線各建一個假型號 |
| 3 | 備援電源算不算進 `battery_*` 統計？ | **建議獨立欄位**，不要混進電池 | 柴發的「放電」是燒油，和電池放電的成本模型完全不同，混在一起會讓節費計算失真。但這會動到 `EnergyInterval` schema |
| 4 | `availability=outage_only` 現在就要偵測停電嗎？ | **先只存欄位、由 `dispatch_command()` 擋人工誤操作** | 偵測停電需要可信的市電狀態訊號（電錶斷線？電壓？UPS 的 on-battery 旗標？），那是另一個設計題 |
| 5 | 分表要不要現在就做 `include_in_balance`？ | **要**，這是防止數字錯誤的關鍵 | 成本極低（一個布林 + aggregator 的一個 filter），而重複計算一旦發生很難察覺 |
| 6 | `AssetRole` 要不要改名？ | 建議 UI 文案改成「量測綁定」，**model 的值不動** | 改 choices 的值要 data migration，收益只有語意清晰；改前端字串就能達到八成效果 |
| 7 | 電錶要不要禁止下任何命令？ | **不要全禁**——`smart-meter` blueprint 本來就有 `set_report_interval` | `is_dispatchable=False` 應該擋的是「能量調度類」命令，不是所有命令。建議在命令定義裡標記哪些是調度類（`"kind": "dispatch"`） |
| 8 | 宣告走 `status` 還是新開 topic？ | **擴充 `status`** | 現成的 retained birth message，不用動 ACL、訂閱清單與韌體流程 |
| 9 | 接受宣告要什麼權限？ | **ADMIN**（等同 `device:write`） | 它實際上就是在改設備能力，和手動編輯同一件事 |
| 10 | 要不要允許「自動接受」白名單？ | **這一輪不要** | 一旦有自動採用的路徑，信任邊界就只剩設定值在守。等實務上真的嫌煩再說 |
| 11 | 純敘述欄位（firmware / ip / rssi）維持自動更新？ | **維持** | 它們不影響 `dispatch_command()` 的判斷，現行行為也已經如此；界線就是「會不會被控制邏輯讀到」 |
| 12 | `AUTO_PROVISION=1` 建的設備預設能力？ | **全部 `False`、`commissioning_state=pending`** | 隔離而非信任；telemetry 照收，命令全擋 |
| 13 | 需量反應要不要專屬的 `can_shed` 旗標？ | **先不加** | 在沒有自動卸載引擎之前只是一個沒人讀的欄位 |
| 14 | 油價要不要帶生效期間？ | **短期單一值 + UI 標明限制，之後再做 `CostParameterSet`** | 正確做法要多一張表；但重算歷史成本時會套到當前油價，這個限制必須讓使用者知道 |
| 15 | session 由 worker 即時算還是排程回算？ | **排程回算**，`rebuild_sessions --hours 2`，每 5 分鐘 | 與既有的 `aggregate_energy --hours 2` 完全對稱；亂序、遲到、worker 重啟三個問題一次消失。代價只有最多 5 分鐘延遲 |
| 16 | `Device` 上要放幾個「最後一次」快取欄位？ | **只放三個 datetime**（charge / discharge / running） | 可索引、可篩選（「30 天沒放電的電池」）；時長與能量去 session 表撈，不值得多維護六個冗餘欄位 |
| 17 | 負載的 session 預設開還是關？ | **關**（`session_tracking_enabled` 依 category：battery `True`、load `False`） | 對照明這種一直通電的迴路沒有意義；要的人自己開 |
| 18 | 分項成本用新表還是 JSON 欄位？ | **新表 `EnergyIntervalCost`** | JSON 無法用 SQL 聚合，「這個月柴發花了多少」會退化成全表掃描 |
| 19 | 節費基準線預設用哪個？ | **`grid_only`**（什麼都沒裝、全買市電） | 多來源之下它回答的問題最清楚；`no_storage` 是現行行為，保留為選項 |
| 20 | 停電期間的節費怎麼記？ | **`null`（未知）**，不要填 0 也不要填市電基準 | 市電斷了就沒有「改買市電」這個替代方案，任何數字都是虛構的 |

---

## 8. 建議的實作順序

1. 能力欄位 + `capability_source` + `commissioning_state` + migration +
   `bootstrap` 預設值（不改行為，純加資料）
2. `dispatch_command()` 的能力檢查 + 錯誤碼 + 測試，**含 §4.1 那個釘住信任
   邊界的測試**
3. `EnergyAsset.include_in_balance` + aggregator 過濾 + 重建區間
4. `DeviceDeclaration` model + 協定 §5.2 的 schema + `StatusProcessor` 的處理
   + `DeviceEvent` / `AuditAction`
5. `availability` 與包絡覆寫欄位（存起來，先只擋人工操作）
6. 前端：能力徽章、命令按鈕停用、資產編輯器、宣告 diff 與接受流程
7. `docs/device-protocol.md` 補上 `attributes` 一節（韌體端要照著寫）
8. `DeviceCategory.load` + `include_in_balance` 套用到 load / ev_charger
   角色 + 重算受影響場域
9. `build_rollups()` 補 `first_value` / `last_value` + `apps/telemetry/energy.py`
   的 `energy_kwh()`（GAUGE 積分 / COUNTER 差值 / counter reset 偵測）
10. `DeviceOperatingSession` + `rebuild_sessions` 排程 + `Device` 的三個快取
    欄位
11. 成本模型註冊表（`apps/ems/costs/`）+ `EnergyIntervalCost` +
    `generator_kwh` + 節費基準線改為可設定、允許 null
12. （另一期）調度引擎：讓 `DispatchWindow` 真的產生命令

第 1、2 步就能擋掉「對只能放電的設備下充電命令」，不必等宣告機制做完。
第 8 步是**修正既有的重複計算**，優先度其實高於它的排序——如果現場已經有人
把個別用電設備建成 `load_meter`，那些場域的 `load_kwh` 現在就是錯的。
