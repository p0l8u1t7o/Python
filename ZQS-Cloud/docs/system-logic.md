# 系統邏輯總覽

這份文件描述系統**目前實際的行為規則**，不看程式碼也能理解。

設計提案在 [device-classification.md](device-classification.md)；那份寫的是
「應該長什麼樣」，這份寫的是「現在是什麼樣」。文件末尾列出兩者的差距。

---

## 1. 設備分類怎麼判定

分類分成三個各自獨立的問題，**不要用其中一個推導另一個**。

### 1.1 「這是什麼」 → `category`

在 blueprint（`DeviceType`）上，11 種：

`battery`、`pcs`、`pv_inverter`、`meter`、`load`、`generator`、`ev_charger`、
`controller`、`sensor`、`gateway`、`other`

**「純量測設備」由 category 判定**，不是由能力旗標推導：只有 `meter` 與
`sensor` 算是量測設備。一盞不可控的照明四個能力旗標全是 `False`，但它是
**負載**，不是電錶。

### 1.2 「能做什麼」 → 四個能力旗標

| 旗標 | 意義 |
| --- | --- |
| `can_charge` | 能在命令下吸收電能 |
| `can_discharge` | 能在命令下輸出電能 |
| `can_export` | 允許把電送回市電側 |
| `is_dispatchable` | 接受任何「調度類」命令 |

**生效值的解析順序**：

1. `Device` 上的覆寫（`null` 代表未覆寫）
2. blueprint 的預設值
3. 沒有 blueprint → **全部視為 `True`**（寬鬆），但 API 回傳
   `capabilities_unchecked: true`，console 會顯示「未指定型號，未做能力檢查」

第 3 點是刻意的：讓沒有 blueprint 的既有設備繼續運作，但把這個缺口顯示出來，
而不是變成一個令人意外的失效。

**blueprint 的預設值依 category 決定**（由 `manage.py bootstrap` 寫入）：

| category | 充 | 放 | 逆送 | 可調度 |
| --- | --- | --- | --- | --- |
| `battery` / `pcs` | ✓ | ✓ | ✓ | ✓ |
| `pv_inverter` | ✗ | ✓ | ✓ | ✓ |
| `generator` | ✗ | ✓ | ✗ | ✓ |
| `ev_charger` | ✓ | ✗ | ✗ | ✓ |
| `meter` / `sensor` | ✗ | ✗ | ✗ | **✗** |
| `load` | ✗ | ✗ | ✗ | ✗ |
| `controller` / `gateway` / `other` | ✗ | ✗ | ✗ | ✓ |

**可控負載**（例如可遠端關閉的冰水機）不需要新旗標：`category=load` 加上
`is_dispatchable=True` 就是它，與純被動負載的差別只在那一個旗標。

### 1.3 「在這個場域扮演什麼」 → `EnergyAsset.role`

六種：`grid_meter`、`load_meter`、`pv`、`battery`、`ev_charger`、`generator`。

這回答的是「這台設備的哪個 metric 供應能量平衡中的哪一條流」，**不是設備
類型**。同一台雙向 PCS 在不同場域可以扮演不同角色。

### 1.4 「它自稱是什麼」 → `DeviceDeclaration`（不可信）

見第 4 節。

### 1.5 設備身分與「類別不可變更」政策

**營運政策：設備的類別永遠不會被修改。** 硬體真的換成不同的東西時，做法是
**建立一台新設備**、把舊的退役——不是把舊那筆資料編輯成新的東西。這樣每一個
歷史數字都還歸屬於實際產生它的那台設備。

**識別碼是 `Device.device_id`**，而且它的約束比表面看起來硬：

- `unique=True` 是**全平台唯一**，不是 per-tenant——因為 topic
  `energy/devices/{device_id}/...` 不含租戶區段，光靠 id 就必須解析出擁有者
- MQTT 帳號 `dev-{org.slug}-{device_id}` 也唯一
- 這個唯一性是**資料庫層級約束，不看退役狀態也不看 soft delete**

所以**接替設備必須換新的識別碼**，這不是設計選擇而是既成事實。現場作業要多
一步：把新的 `device_id` 寫進替換硬體的設定，並使用新發的 MQTT 帳密。建議
命名慣例例如 `ZQS-BESS-0001` → `ZQS-BESS-0001-R2`（替換精靈預設就這樣填）。

**`serial_number` 沒有唯一性約束**，目前只是自由文字，不能拿來當識別碼。

---

## 2. 能量平衡：誰算、誰不算

### 2.1 基本規則

**每一條能量流，恰好要有一條量測路徑。**

一個 `EnergyAsset` 只有在 `include_in_balance = True`（預設）時才會進入場域的
能量平衡。設為 `False` 的資產仍然：

- 有自己的圖表與歷史
- 出現在設備列表與地圖
- 未來會有自己的耗能統計

但**不會**被加進 `load_kwh`、`grid_import_kwh` 等場域層級的數字。

### 2.2 什麼時候該設 `False`

| 情境 | 設定 |
| --- | --- |
| 總負載表 + 個別機器的分表 | 總表 `True`，個別機器 `False` |
| 沒有總表、逐饋線量測 | 所有饋線表 `True`（相加剛好涵蓋全部） |
| 市電總表以外的第二顆電錶 | `False` |
| 兩台 PV 逆變器 | **都 `True`**（實體上是兩個來源，相加正確） |
| 兩組電池 | **都 `True`**（同上） |
| 總表已含 EV 充電樁，又單獨量測充電樁 | 充電樁 `False` |

判準：**這個量測涵蓋的電流，是否已經被另一個 `True` 的量測涵蓋過。**

### 2.3 各角色進入哪一條流

```
grid_meter                → grid_import_kwh / grid_export_kwh / peak_import_kw
pv                        → pv_kwh
battery                   → battery_charge_kwh / battery_discharge_kwh + SOC
generator                 → generator_kwh          ← 獨立欄位
load_meter, ev_charger    → load_kwh
```

**`generator` 為什麼獨立於 `battery_*`**：往返效率的定義是
`discharge / charge`。柴發只放不充，把它的輸出併進 `battery_discharge_kwh`
會算出大於 1 的往返效率。

### 2.4 沒有負載表時的推導

若場域沒有任何 `include_in_balance=True` 的 load 角色資產，負載由節點平衡
反推：

```
load = grid_import − grid_export + pv + battery_discharge − battery_charge + generator
```

結果會被 clamp 到 ≥ 0。

### 2.5 積分方法

功率轉能量用**前值保持（zero-order hold）**：每個樣本的值假設保持到下一個
樣本為止。**不是梯形法。**

- 對回報頻率遠高於變化尺度的訊號，誤差可忽略
- 對馬達啟停這種突變負載有系統性偏差，方向取決於變化是上升或下降
- `coverage`（0..1）記錄該區間實際被樣本涵蓋的比例——這是品質指標，低於 0.8
  的區間不該被當成確定的數字
- recording policy 的 `max_interval_seconds`（心跳）決定誤差上界。要做精確
  耗能統計的設備，建議把心跳調到 300 秒以內

**若設備同時回報累計電能（counter），一律優先用 counter 差值**——那是設備
自己累計的，沒有取樣誤差。

### 2.6 跨場域彙總

彙總多個場域時（例如整個廠區）：

- **能量與金額**：直接相加
- **尖峰**：先把同一時間區間內各場域相加，再取這些總和的最大值。**絕不是各
  場域尖峰相加**（那會高估）。回應中的 `peak_basis` 標示：單一場域是
  `measured`，多場域是 `coincident_estimate`
- **比率**（自用率、自給率、往返效率）：分子分母各自加總後再除，**不是平均**
- **幣別**：各場域幣別不一致時，數字照給但 `currency` 回空字串

---

## 3. 命令什麼情況會被擋

所有下行命令都經過同一個關卡（`dispatch_command()`），依序檢查：

| 順序 | 檢查 | 錯誤碼 | HTTP |
| --- | --- | --- | --- |
| 1 | 設備已停用 | `device_disabled` | 409 |
| 2 | 命令不在 blueprint 的目錄裡 | `unknown_command` | 422 |
| 3 | 角色權限不足 | — | 403 |
| 4 | 參數不符 JSON-schema | `parameter_out_of_range` 等 | 422 |
| 5 | 設備尚未驗收（`pending`），且這是調度類命令 | `device_unconfirmed` | 409 |
| 6 | `is_dispatchable=False`，且這是調度類命令 | `asset_not_dispatchable` | 422 |
| 7 | 缺少該命令需要的能力 | `capability_not_supported` | 422 |
| 8 | 該設定會造成逆送，但不允許 | `export_not_permitted` | 422 |

生命週期與身分相關的攔截（都只作用於調度類命令）：

| 情況 | 錯誤碼 | HTTP |
| --- | --- | --- |
| 尚未驗收 | `device_unconfirmed` | 409 |
| 已退役 | `device_retired` | 409 |
| 暫停中 | `device_suspended` | 409 |
| 驗收時被拒絕 | `device_rejected` | 409 |
| 宣告類別與註冊不符 | `device_identity_mismatch` | 409 |

### 3.1 命令需要什麼能力，由「名稱**加上**參數值」決定

只看命令名稱是不夠的：

| 命令與參數 | 需要的能力 |
| --- | --- |
| `set_power_setpoint`，`power_w < 0` | `can_charge`（負值就是充電） |
| `set_power_setpoint`，`power_w > 0` | `can_discharge` |
| `set_power_setpoint`，`power_w = 0` | 不需要任何能力 |
| `set_mode`，`mode = charge` | `can_charge` |
| `set_mode`，`mode = discharge` | `can_discharge` |
| `set_mode`，`mode = auto` | **兩者都要**（auto 可能往任一方向） |
| `set_mode`，`mode = idle` / `standby` | 不需要 |
| `set_export_limit`，`limit_w > 0` | `can_export` |
| `set_export_limit`，`limit_w = 0` | 不需要（設 0 是**禁止**逆送，擋它反而顛倒） |

### 3.2 調度類 vs 設定類命令

blueprint 的命令定義可以標 `"kind": "config"`。設定類命令**不受
`is_dispatchable` 與 `commissioning_state` 限制**。

目前標為 `config` 的：`set_report_interval`、`sync_time`。

所以一顆電錶（`is_dispatchable=False`）仍然可以被要求改變回報頻率——那不會
移動任何電力。

### 3.3 生命週期狀態

見 §11。

---

## 4. 設備宣告：可以說，不能做

設備可以在 `status` 的 birth message 裡帶一個 `attributes` 物件，宣告自己的
類別、能力與額定值（格式見 [device-protocol.md](device-protocol.md) §3.7）。

### 4.1 絕對規則

**控制與安全檢查只讀已確認的欄位，永遠不讀設備宣告。**

宣告存在獨立的 `DeviceDeclaration` 表，而不是 `Device` 上的
`declared_*` 欄位。這不只是整潔問題：`dispatch_command()` 拿到的是 `Device`，
而 `Device` 上根本沒有承載宣告的欄位，因此想誤用也無從誤用。

### 4.2 收到宣告時會發生什麼

1. 沒有 `attributes` → 什麼都不做
2. `schema_version` 不認得 → 記一筆 `DeviceEvent`（`declaration.unsupported_version`），忽略內容
3. 與上一次宣告**完全相同** → 只更新接收時間，**不產生待審核**
   （設備每次重連都會發 birth message，否則審核佇列會被洗版）
4. 有變動 → 覆寫宣告記錄、算出 diff、狀態設為 `mismatched`、發一筆
   `DeviceEvent`（`declaration.changed`，或類別不同時的
   `declaration.identity_mismatch`）
5. **任何情況下都不改動 `Device` 的能力欄位**

### 4.3 有人偽造宣告會怎樣

1. 攻擊者必須先持有該設備的 MQTT 憑證（EMQX auth webhook 是 fail closed 的）
2. 他讓設備宣告 `can_charge: true`
3. 宣告存起來，狀態 `mismatched`
4. `Device.can_charge` **不變**，充電命令仍被 `capability_not_supported` 擋下
5. 操作者在設備頁看到「宣告與生效值不符」的 diff

**最壞情況是一個誤導操作者的提示，不是一個可執行的能力。**

### 4.4 採用宣告：只在驗收階段，只有一次

`POST /devices/{id}/declaration/review` `{"accept": true}`，需要 **ADMIN**，
而且**只在設備仍是 `pending` 時可用**。之後回 409 `declaration_not_adoptable`。

理由就是 §1.5 的政策：類別不會改變，所以驗收之後的分歧不是一個待批准的變更，
而是「硬體大概被換掉了」的訊號，正確的處置是建立接替設備。

採用後：能力欄位被寫入、`capability_source` 標為 `device`、生命週期轉為
`active`，並在 audit 留下 `device.declaration_accepted`。

`{"accept": false}` 是**知悉**（acknowledge）：宣告狀態改為 `acknowledged`，
設備完全不動。**知悉不會解除身分不符造成的命令凍結**——看到問題不等於解決
問題。

### 4.5 宣告狀態

| 狀態 | 意義 |
| --- | --- |
| `matched` | 與註冊資料一致 |
| `mismatched` | 有差異，尚未處理 |
| `acknowledged` | 差異已知悉，不再提示 |

### 4.6 身分不符：資料照收，命令凍結

當宣告的 `category` 與註冊的 blueprint 類別不同時：

1. **telemetry 照常接收**——資料不能丟
2. 記一筆 `DeviceEvent`（level `error`、code `declaration.identity_mismatch`）
3. 宣告標記 `identity_mismatch = true`
4. **所有調度類命令被拒絕**，回 `device_identity_mismatch`（409）
5. console 顯眼提示，並提供「替換設備」入口

第 4 點是重點：**身分不確定時，控制要收緊而不是照常放行。** 如果不確定這台
是什麼，就不該對它下能量指令。

只有**類別**不同會凍結命令；單純的能力差異只會標記為 `mismatched`。

### 4.5 哪些欄位維持自動更新

`firmware`、`hardware`、`ip`、`rssi`、`location` 仍然直接寫進 `Device`——
它們是純敘述性的，不影響任何控制決策。

界線很清楚：**這個值會不會被 `dispatch_command()` 讀到。**

---

## 5. 哪些情況記 `null`

系統的原則是：**不知道就記成不知道。** 把未知填成 0 會讓錯誤變成看起來合理的
數字，那比明顯的空白更難發現。

| 情況 | 記法 |
| --- | --- |
| 累計計數器倒退（換表／韌體重置／未知的溢位） | 該區間的 delta 記 `null`，**不是 0 也不是負數**，並發 `DeviceEvent`（`counter.reset`） |
| 計數器倒退但 `Metric.counter_max` 有值 | 做 wrap 修正 `(counter_max − first) + last`，並標記 `counter_reset` |
| 計數器倒退幅度小於容差（浮點雜訊） | 記 0 |
| 該區間完全沒有樣本 | 能量記 `null`，`basis = "unknown"` |
| 子樹裡沒有任何場域有能源資料 | `/sites/{id}/summary` 的 `energy` 回 `null` |
| 跨場域幣別不一致 | 數字照給，`currency` 回空字串 |

---

## 6. 成本與節費（目前狀態）

**目前只計算市電成本。**

```
energy_cost     = grid_import_kwh × 該時段電價
export_revenue  = grid_export_kwh × 該時段躉售價
estimated_savings = baseline_cost − actual_cost
其中 baseline = 同樣的負載與 PV，但沒有電池
```

電價由 `Tariff` 的時段定義解析（支援跨午夜的時段）。

**電池放電與柴發輸出目前不計價。** 多來源成本模型（電池循環成本、柴發油耗
乘油價加維護、負節費、停電期間不計節費）已完成設計但**尚未實作**——見第 8 節。

---

## 7. 運轉 session（尚未實作）

「最後一次充電／放電／運轉的時間與持續多久」已完成設計但**尚未實作**。
見第 8 節。

---

## 8. 已實作 vs 僅完成設計

| 項目 | 狀態 |
| --- | --- |
| 設備能力（4 旗標、三層解析、category 預設） | **已實作** |
| 命令能力檢查（含依參數值判定意圖） | **已實作** |
| 驗收狀態與自動建檔隔離 | **已實作** |
| `include_in_balance` 與重複計算修正 | **已實作** |
| `generator` 角色與 `generator_kwh` | **已實作** |
| `Rollup.first_value` / `last_value` | **已實作** |
| 累計計數器差值與 reset 記 `null` | **已實作**（`apps/telemetry/energy.py`） |
| 設備宣告、diff、審核、audit | **已實作** |
| 生命週期五狀態與 `is_enabled` 同步 | **已實作** |
| 退役不 soft delete、退役可逆 | **已實作** |
| `replaced_by` 與替換 API | **已實作** |
| 身分不符偵測與命令凍結 | **已實作** |
| 報表串接 `follow_replacements`（切點不相加） | **已實作** |
| `Metric.counter_max` | **已實作**（欄位就緒，內建目錄尚未填值） |
| 個別設備耗能的 API 端點 | 尚未實作（計算函式已就緒） |
| 運轉 session（`DeviceOperatingSession`） | 僅設計 |
| 多來源成本模型（`apps/ems/costs/`） | 僅設計 |
| `EnergyIntervalCost` 分項成本 | 僅設計 |
| 節費基準線可設定、負節費、停電記 `null` | 僅設計 |
| `EnergyAsset` 的 session 參數與成本參數 | 僅設計 |
| 調度引擎（讓 `DispatchWindow` 產生命令） | 明確不做（待拍板 #1） |

---

## 9. 升級既有安裝要跑什麼

```bash
python manage.py migrate
python manage.py bootstrap --update-existing
```

第二行是關鍵：它依 category 把能力預設值寫進內建 blueprint。沒有它，所有
blueprint 的四個旗標都會是欄位預設值（`can_charge=False`、
`is_dispatchable=True`），電池會無法充電。

**既有資料的歸屬**：

- 所有既有設備 → `commissioning_state = confirmed`，四個能力欄位為 `null`
  （繼承 blueprint）
- 所有既有場域資產 → `include_in_balance = True`（行為不變）
- 所有既有能源區間 → `generator_kwh = 0.0`

既有設備的生命週期歸類（由 migration `0006_device_lifecycle` 的 data
migration 處理）：

- 原本的 `confirmed` → `active`
- 原本手動設了 `is_enabled=False` 的 → `suspended`（保留原意圖，但改用
  生命週期表達，兩個欄位從此不會矛盾）
- 既有宣告：有 diff 的 → `mismatched`，沒有的 → `matched`；`category` 有差異
  的另外標記 `identity_mismatch`

**若現場已經把個別用電設備建成 `load_meter`**，那些場域的 `load_kwh` 在此之前
就是錯的（重複計算）。把個別設備改成 `include_in_balance=False` 之後，需要
重算：

```
POST /api/ems/sites/{site_id}/rebuild-intervals?start=...&end=...
```

單次重算上限 90 天。

---

## 10. 設備替換

### 10.1 什麼時候要替換

硬體換成**不同類型或不同能力**的東西時。同型號的維修、更換零件、重新校正
都不算——那還是同一台設備。

### 10.2 一次呼叫，一個交易

```
POST /api/devices/{old_id}/replace
{"device_id": "ZQS-BESS-0001-R2", "name": "…", "serial_number": "…", "reason": "…"}
```

需要 **ADMIN**。單一交易內完成：

1. 以新 `device_id` 建立接替設備，繼承場域、blueprint、recording policy、座標
2. **搬移所有 `EnergyAsset` 綁定**
3. 搬移 device 層級的 alert 規則（加新的、移除舊的）
4. 舊設備設 `replaced_by` 指向新設備，並轉為 `retired`
5. 發放新的 MQTT 憑證（密碼只回傳一次）
6. 記一筆 audit（`device.replaced`）

回應會回報搬了幾筆資產綁定與幾條規則。

### 10.3 為什麼要一次做完

第 2 步是不能漏的那一步。綁定留在一台不再回報的設備上**不會產生任何錯誤**
——積分回空，場域數字就靜靜地少一塊。如果那是市電總表，整個場域會顯示成
沒有用電。分成多步操作就會出現「舊的停了、新的還沒綁」的空窗。

### 10.4 退役／暫停時的保護

直接把設備退役或暫停時，若仍有 `is_active=True` 的 `EnergyAsset` 綁在上面，
會被擋下：

```
409 device_in_energy_model
details.assets = [{asset_id, role, site}, …]
```

替換流程不受此限——它在同一個交易裡已經先把綁定搬走了。

### 10.5 報表串接

`POST /api/telemetry/series` 加 `"follow_replacements": true`，**預設關閉**。

關閉時：一台設備一條序列，就是資料原本的樣子。
開啟時：整條替換鏈合併成一條邏輯序列，回應的 `device_ids` 列出串了哪幾台。

**串接時同一時刻只取一台，以退役時間為切點。** 每台設備只貢獻
`[前一台的退役時間, 自己的退役時間)` 這個窗口內的資料。

這條規則不是形式主義：退役的硬體常常還在送資料——留在工作台上通電、或只是
還沒拔線——所以兩台在牆上時間會重疊。把重疊相加會**灌水能量、並製造出一個
從未發生過的尖峰**，而且兩者在圖表上都看起來很合理。

預設關閉的理由：串接是一種**解讀**（假設接替設備與前一台等價），不是資料本身。

---

## 11. 生命週期狀態

### 11.1 五個狀態

| 狀態 | 收 telemetry | 可連線 | 可下調度命令 | 用途 |
| --- | --- | --- | --- | --- |
| `pending` | ✓ | ✓ | ✗ | 自動建檔而來，等待驗收 |
| `active` | ✓ | ✓ | ✓ | 正常運轉 |
| `suspended` | ✗ | ✗ | ✗ | 暫時停用（維修中） |
| `retired` | ✗ | ✗ | ✗ | 已退役，被接替或不再使用 |
| `rejected` | ✗ | ✗ | ✗ | 驗收時判定不該存在 |

`pending` 照常收資料是刻意的：操作者需要看到它實際送什麼，才能判斷這是什麼
東西。

### 11.2 三個旗標的分工

| 欄位 | 回答什麼 | 誰設定 |
| --- | --- | --- |
| `commissioning_state` | 這台處於什麼階段 | 操作者，透過 API |
| `is_enabled` | 要不要收它的資料 | **不再手動設定**——由 service 依生命週期同步 |
| `deleted_at`（soft delete） | 這筆紀錄該不該存在 | 只用於「建錯了，當作沒發生過」 |

`is_enabled` 仍然是 ingest 路徑（ingestor、worker、EMQX auth webhook）唯一
讀的欄位，那條熱路徑沒有改變。改變的是沒有人再單獨設定它，所以「已退役」和
「可以連線」不可能互相矛盾。

**退役絕不使用 soft delete。** 軟刪除會讓設備從 API 消失，歷史就沒有入口了。
退役的設備照常查得到、歷史照常可讀，只是不能連線也不能被指揮。

### 11.3 退役可逆

ADMIN 可以把 `retired` 改回 `active`（硬體確實會從維修廠回來），並留下
`device.restored` 的 audit 記錄。

兩個要處理的情境：

- **接替設備還在服役** → 回 409 `successor_still_active`，要求先把接替設備
  退役或暫停。否則兩台會同時宣稱自己是同一件設備，串接報表就會有歧義。
- **識別碼衝突** → **不會發生**。`device_id` 全平台唯一，而退役的設備從來
  沒有交還自己的識別碼，所以復役永遠不會撞號。

復役時 `retired_at` 與 `replaced_by` 一併清空——它又是現役設備了，留著退役
時間會讓串接報表把它裁掉。

```
POST /api/devices/{id}/lifecycle  {"state": "active", "reason": "…"}
```

---
