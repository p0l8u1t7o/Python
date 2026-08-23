# ZQS Cloud — 下一階段開發規格

> 交接給 Claude Code（VS Code）。建議放在專案根目錄或 `docs/` 下，並在 `CLAUDE.md` 裡加一行指向它。
>
> 基準版本：v0.2 客戶展示版（2026-08-22）
> 目標：把「完整的 SCADA + 反應式 EMS」推進成「真正做營利最大化的表後儲能產品」

---

## 0. 先讀這裡：現況判斷

這個專案**不是半成品**。以下全部已實作且有測試釘住，動它們之前先確認你真的理解為什麼那樣寫：

| 領域 | 狀態 |
|---|---|
| Sparkplug B 擷取、設備註冊表、藍圖、能力旗標、生命週期、替換 | 完成 |
| 遙測目錄、記錄策略、counter 差值、積分與涵蓋率 | 完成 |
| `EnergyAsset` 角色綁定、15 分鐘 `EnergyInterval`、能源平衡 | 完成 |
| 成本模型註冊表（`grid_tariff` / `battery_cycle` / `diesel_fuel` / `grid_export`）、`EnergyIntervalCost` | 完成 |
| 電價（台電 114 年三個內建方案、TOU 時段解析、`demand_charge_per_kw`） | 完成 |
| 五個調度策略的**實際算術**（`apps/ems/strategy.py`） | 完成 |
| 調度引擎權威順序、包絡夾限、健康約束、deadband、冪等 | 完成 |
| 需量費受益計算（含台電 2 倍／3 倍超約規則） | 完成 |
| 工作流程引擎（token 持久化）、告警、通知、稽核、RBAC、多租戶 | 完成 |
| 設備模擬器（真實物理模型的外部 MQTT 客戶端） | 完成 |
| `scripts/verify_calculations.py`（3,300+ 交叉比對）、Playwright e2e | 完成 |

**真正的缺口是兩端：「規劃」與「結算」。** 中間的執行層已經很扎實。

---

## 1. 不可打破的既有設計決定

這些是實機踩過才寫成這樣的。重構時如果覺得某一條「多餘」，先去 `docs/system-logic.html`
與 `docs/codebase-guide.html` 找對應段落，那裡寫了理由。

1. **`dispatch_command()` 是唯一的下行閘門。** 排程引擎、工作流程、人工操作走同一條路，
   沒有特權後門。新增任何自動控制路徑都必須經過它。
2. **「沒有讀值」永遠不等於 0。** 讀值缺失或過舊（預設 180 秒）時走「無讀值」分支，
   不要用 0 代入判斷式。
3. **未知的成本模型 key 要 raise，不要靜默回 0。** 成本靜默歸零是最難發現的錯誤。
4. **節費允許為負，停電區間記 `null`。** 不要夾到 0，不要填市電基準。
5. **counter 倒退記 `null`。** 除非 `Metric.counter_max` 有值。
6. **策略決策先還原場域自身需量**：`native = grid_kw + battery_kw`
   （`_native_demand_kw()`）。少了這一步電池會追自己的尾巴，有測試釘住。
7. **兩條路徑刻意不同**：排程用 `clamp_to_plan()` **夾住**，手動 API 用
   `assert_within_plan()` **拒絕**（422 `storage_plan_limit`）。
8. **只在目標值改變超過 `SETPOINT_DEADBAND_W`（500 W）時送命令。** 靠
   `idempotency_key` 的 `dispatch:` 前綴辨識自己上次送的值。
9. **SOC 限制只在讀得到即時 SOC 時套用。** 不猜。
10. **銘牌 > 包絡 > 資產覆寫，取最嚴**：`effective = min(rated, plan, asset)`，忽略 `None`。
11. **設備 category 驗收後永不修改。** 硬體換了就建接替設備。
12. **回覆與註解用繁體中文，識別名用英文。** 沿用既有 docstring 風格：
    寫「為什麼」而不是「做什麼」，並標明這條規則是為了擋掉哪個失效模式。

---

## 2. 開發環境

```powershell
.\scripts\dev.ps1 -Setup      # 第一次：建環境、遷移、種子、歷史資料
.\scripts\dev.ps1             # 日常，約 5 秒起整個堆疊
.\scripts\stop.ps1
.\scripts\sim-console.ps1     # 設備模擬器主控台
.\scripts\reset-demo.ps1      # 清庫重建展示租戶
```

- Windows 原生，Python 走 `.venv\Scripts\python.exe`
- 預設 SQLite + `BUS_BACKEND=memory` + 內建 broker；`-Full` 才需要 Redis / EMQX
- 已設的環境變數優先於 `.env`（`load_dotenv(override=False)`）
- `apps/devices/registry.py` 是 TTL 快取（預設 30 秒），建立／刪除設備後要
  `get_registry().invalidate()`，測試裡也要記得叫

驗證：

```powershell
.venv\Scripts\python.exe manage.py test
.venv\Scripts\python.exe scripts\verify_calculations.py
.venv\Scripts\python.exe manage.py run_dispatch --dry-run
cd frontend; npx playwright test
```

---

## 3. 工作項目

六項，建議照順序做。**W1、W3 可並行，W2 依賴 W1。**
每一項獨立可交付、可 review、可回退，不要合併成一個大 PR。

---

### W1 — `apps/ems/forecast.py`：負載與 PV 預測

**現況**：整個系統沒有「未來」。所有策略都是反應式的——
`demand_cap` 是「需量已經超過上限就放電」，`tou_arbitrage` 是「今天最貴／最便宜的時段」。

**為什麼要做**：這是後面三項的共同前提。沒有預測就沒有 SOC 日內規劃，
沒有窗口積分控制，也沒有辦法把套利與需量管理疊加。

**要做什麼**：一個純函式模組，從 `EnergyInterval` 歷史推出未來 N 個 15 分鐘區間的預測。

先做最簡單但有用的版本，不要一上來就上機器學習：

- **負載**：取同一場域、同一 weekday、最近 K 週（建議 4）的同時段
  `load_kwh` 中位數，再乘上「近 3 天實測 / 同期預測」的漂移係數。
- **PV**：同上，但用 `pv_kwh`，並保留一個可注入天氣係數的介面（先傳 1.0）。
- **誤差分布**：每次預測都要留下記錄，之後回算 P50 / P90 誤差。這是 W2 要用的。

**介面**：

```python
@dataclass(slots=True)
class ForecastPoint:
    starts_at: dt.datetime      # UTC，區間起點
    load_kw: float | None       # 該區間平均功率
    pv_kw: float | None
    confidence: str             # "measured" | "estimated" | "unknown"，沿用 EnergyIntervalCost.basis 的語彙

def forecast_site(
    site_id, moment: dt.datetime, horizon_hours: int = 24
) -> list[ForecastPoint]:
    """未來 horizon_hours 的負載與 PV 預測，15 分鐘解析度。

    歷史不足時回傳 confidence="unknown" 的點而不是拋例外——策略端必須
    能自己決定「沒有預測時怎麼辦」，而不是整個調度掛掉。
    """

def forecast_error_stats(site_id, days: int = 14) -> ErrorStats:
    """回算最近 days 天的預測誤差分布。W2 的保險餘裕由這裡來。"""
```

**資料表**：新增 `LoadForecast`（`site` × `starts_at` × `made_at` 唯一）。
保留 `made_at` 是為了能回算「當時預測的」而不是「事後最佳的」——
沒有這個欄位就無法評估預測品質。時間一律存 UTC。

**驗收**：
- 用 `generate_history --days 30` 的資料，對已知的歷史區間做 backtest，
  MAPE 應該在 10–15% 以內（廠房負載規律性高）
- 歷史不足 2 週時回 `confidence="unknown"`，且不 raise
- 週末／假日不會被工作日污染
- 新增 `tests/test_forecast.py`

**不要做**：不要接外部氣象 API（留介面就好）、不要引入 sklearn / prophet
（產線環境多一個依賴就是多一個離線安裝的麻煩）、不要動 `aggregator.py`。

---

### W2 — 需量窗口積分控制（改 `demand_cap`）

**現況**（`apps/ems/strategy.py::demand_cap`）：拿當下的 native demand 跟上限比，
超過就放差額。

**問題**：台電計費單位是 15 分鐘**平均**功率，這是積分量。
引擎在窗口第 10 分鐘看到 745 kW，前 9 分鐘的累積已經寫死——這個窗口的平均值
可能已經注定超標，此時放電只能壓低後 5 分鐘，救不回來。

模擬器的負載是正弦曲線 ±2% 雜訊所以看不出問題；真實廠房是階躍的
（一台冰水主機啟動就是 200 kW）。**這會是上線後第一個被客戶抓到的缺陷。**

**要做什麼**：

```
窗口起點 = moment 對齊到 15 分鐘邊界
elapsed_h = (moment - 窗口起點) 的小時數
remaining_h = 0.25 - elapsed_h

accumulated_kwh = 窗口起點至今的 native 用電（對功率積分，用 telemetry）
predicted_rest_kwh = remaining_h × 預測 native 功率   # W1 提供，退回當前值
projected_demand_kw = (accumulated_kwh + predicted_rest_kwh) / 0.25

若 projected_demand_kw > ceiling：
    需要削減的 kWh = (projected_demand_kw - ceiling) × 0.25
    放電功率 = 需要削減的 kWh / remaining_h
```

**必須處理的邊界**（這幾個沒處理就會出事）：

- `remaining_h → 0` 時上式會爆到無限大。設一個 `MIN_REMAINING_H`
  （建議 60 秒 = 0.0167 h），低於它就維持上一輪設定值到窗口結束，不要重算。
- 窗口切換時**狀態要歸零**，且不要在邊界瞬間把設定點歸零再重建——
  這會在每個 15 分鐘邊界產生一次功率突跳。
- 保險餘裕由 W1 的 `forecast_error_stats()` 決定（建議用 P90 誤差），
  取代現在寫死的「契約容量 95%」。沒有誤差統計時退回 95%。
- 積分要用「前值保持」與既有 `integrate_power()` 一致，且
  `coverage < 0.8` 的窗口要標記為不可信，此時退回現在的瞬時邏輯而不是硬算。

**保留**：離峰回充的邏輯（充電只到需量餘裕、只在最便宜時段）已經是對的，不要動。

**介面**：新增 `apps/ems/demand_window.py`，`demand_cap()` 呼叫它。
分成獨立模組是因為 W6 的邊緣側也要用同一套算術。

```python
@dataclass(slots=True)
class WindowState:
    window_start: dt.datetime
    accumulated_kwh: float
    coverage: float             # 0–1，樣本涵蓋率
    is_trustworthy: bool

def window_state(site_id, moment) -> WindowState: ...
def required_discharge_kw(state: WindowState, ceiling_kw: float,
                          predicted_kw: float, moment) -> float:
    """為了讓本窗口平均 ≤ ceiling，現在必須放多少 kW。負值代表有充電餘裕。"""
```

**驗收**（測試要釘死這幾個情境）：
- 階躍負載：窗口前 5 分鐘 400 kW、之後跳到 900 kW，上限 650 kW →
  引擎在第 6 分鐘就要下足夠的放電，使窗口末端平均 ≤ 650
- `remaining_h` 小於門檻時不重算、不歸零
- 窗口邊界不產生功率突跳
- 涵蓋率不足時退回舊邏輯且理由字串說明原因
- 既有的 `tests/test_storage_strategies.py::DemandCapTests` 全部仍要通過
  （尤其 `test_a_charging_battery_does_not_look_like_an_excursion`
  與 `test_offpeak_recharge_never_exceeds_the_headroom`）

**注意**：策略目前跑在排程器週期（開發 60 秒、正式 300 秒）。
**300 秒對窗口控制太粗**——一個 15 分鐘窗口只有 3 個決策點。
這一項要把 `demand_cap` 場域的評估週期獨立出來（建議 15–30 秒），
或在 W6 把積分控制下放到邊緣。先做前者，在 PR 說明裡標註這是暫時方案。

---

### W3 — `apps/ems/backtest.py`：策略回放框架

**現況**：`verify_calculations.py` 驗證「數字彼此一致」，這很有價值，
但它不回答「策略 A 比策略 B 多賺多少」。

**為什麼要做**：投入最小、槓桿最大。有了它才能調參有依據、
上新策略前先量化、對客戶用**他自己的歷史資料**證明效益。
W2、W5 的成效也都要靠它證明。

**要做什麼**：給定一段歷史 `EnergyInterval` + 電價 + 電池參數，
重放任意 `StoragePlan` 設定，輸出電費、需量費、循環數。

關鍵設計：**重放時必須從 native 量重建**（負載、PV），
不能直接用歷史電表值——歷史電表值裡已經包含了當時電池的動作。

```python
@dataclass(slots=True)
class BacktestResult:
    energy_cost: float
    demand_charge: float
    penalty: float              # 超約罰款
    cycle_cost: float           # 走 costs/battery_cycle
    total: float
    peak_demand_kw: float
    equivalent_cycles: float
    intervals: list[...]        # 逐區間明細，供畫圖

def replay(site_id, plan: StoragePlan, start, end,
           battery_kwh: float, battery_kw: float) -> BacktestResult:
    """用歷史負載與 PV 重放一組方案設定。

    電池以簡單能量積分模擬（同 simulator/ 的物理模型），受 SOC 上下限
    與功率限值約束。不模擬效率曲線與溫度——那個精度回測用不到。
    """
```

**CLI**：`manage.py backtest --site hsinchu-a --plan <id|json> --days 30 --compare <plan2>`
輸出對照表。這是這一項最終要交付的東西。

**驗收**：
- 對展示租戶跑 30 天，`demand_cap` vs `tou_arbitrage` vs `manual` 三者的
  總成本差異合理且可解釋
- 重放「當時實際用的方案」，結果應接近實際 `EnergyInterval` 的成本
  （差異來自模擬精度，標明容許範圍）
- 電池模擬不會違反 SOC 上下限

**不要做**：不要寫進資料庫（回測是純計算，結果回傳即可）、
不要做前端頁面（先 CLI，UI 之後再說）。

---

### W4 — 月結算表

**現況**：`docs/system-logic.html` §8 自己列的——
「月尖峰需量費：受益面已實作；**進入月結算、計入 `total_energy_cost` 尚未實作
——需要一張月結算表**」。

**為什麼要做**：現在的需量費是「任意窗口內最高需量 × 月費率」的估算
（頁面已誠實標注）。但客戶會拿真帳單來比。沒有月結算就沒有對帳、
沒有可寫進合約的 ROI、也沒辦法回答「你的契約容量應該從 680 降到 600」
——後者往往比調度策略更值錢。

**要做什麼**：新增 `MonthlySettlement`（`site` × `billing_month` 唯一）：

```
site, billing_month (該場域時區的當地月份)
tariff_snapshot        JSON —— 結算當下的電價快照，之後改電價不影響已結算的月份
peak_demand_kw         該月最高的 15 分鐘需量
peak_occurred_at
contract_capacity_kw
energy_charge          流動電費
demand_charge          基本電費
excess_penalty         超約罰款（沿用 excess_charge()）
export_revenue
total
baseline_total         同一個月的基準線（沿用 StoragePlan.savings_baseline）
savings                total - baseline_total，允許為負
basis                  measured | estimated | unknown，取月內最差的
finalized_at           null = 進行中的月份，可重算；有值 = 已封存
```

`tariff_snapshot` 是重點：電價會被編輯（電價表單上就寫著「修改電價會連帶改變
這些場域的所有電費」），已結算的月份不能被回頭改掉。

**計算命令**：`manage.py settle_month --month 2026-07`，冪等
（與 `aggregate_energy --hours 2` 同樣的重疊回算慣例），
排程器每天跑一次當月與上個月。上個月在次月 5 號自動 `finalized_at`。

**同時處理**：`CostParameterSet` 的時間性（目前標為「僅設計」）。
沒有它，重算三個月前的柴發成本會套到今天的油價。
如果範圍太大，至少在結算時把當時的成本參數一併寫進 snapshot。

**驗收**：
- 整月窗口的 `/ems/cost-overview` 數字 = `MonthlySettlement` 的數字
- 結算後修改電價，已結算月份的數字不變
- 重跑 `settle_month` 結果相同（冪等）
- `verify_calculations.py` 加入月結算的交叉比對

**不要做**：不要改 `EnergyInterval` 上那三個總計欄位的語意
（`energy_cost` / `export_revenue` / `estimated_savings`）——
儀表板、`_totals()`、跨場域 rollup 全都讀它們。

---

### W5 — 策略疊加仲裁

**現況**：`StoragePlan` 是 `OneToOne(site)`，`strategy` 是單一枚舉。
台中廠選了 `tou_arbitrage` 就**不做需量管理**，A 棟選了 `demand_cap` 就**不做套利**。

**問題**：這是營利最大化最大的單一結構缺口。台中廠 1 MW / 2 MWh 的電池，
離峰充飽之後尖峰放電本來就同時在削需量——這個價值現在既沒被規劃也沒被計算。
反過來 `demand_cap` 的離峰回充已經在挑最便宜的時段，那已經是半個套利了，
只是沒被承認。

**要做什麼**：把策略從「單選」改成「約束 + 目標」。**不要一步跳到 MILP**——
先做優先序仲裁，等 W3 的回測證明還有可觀的剩餘價值再考慮最佳化求解器。

```
硬約束（違反的成本遠高於任何收益）：
  1. 需量上限          —— 超約罰款是台電費率的 2–3 倍
  2. 備援保留 SOC
  3. 電池健康（溫度、日循環）
  4. 運轉包絡（功率、SOC 上下限）

在剩餘自由度內，依貨幣化價值排序：
  5. 套利價差 −  battery_cycle 的循環成本
  6. PV 自用（省下的購電價 − 躉售價）
```

實作上：把 `strategy_power_w()` 從「一個策略算一個值」改成
「各策略各提出一個 `StrategyProposal`（功率、貨幣化價值、是否為硬約束），
再由仲裁器解算」。`decide()` 的權威順序（DR > 排程窗 > 策略 > 包絡+健康）
已經是這個形狀，只是目前三者**互斥**而不是**疊加**。

**資料模型**：`StoragePlan.strategy` 從單選改成可多選
（保留單選作為相容路徑，既有資料自動遷移成單元素清單）。
順帶處理 `OneToOne(site)` 的限制——一個場域兩組電池
（一組套利、一組備援）現在分不開，考慮把包絡下放到 `EnergyAsset`。

**驗收**：
- 用 W3 回測證明：台中廠「套利 + 需量管理」的 30 天總成本
  低於單獨任一策略，且差額可以逐項解釋
- 硬約束永遠不被軟目標推翻——測試要有一個「套利收益很高但會超約」的情境，
  斷言引擎選擇不套利
- 既有單策略設定的行為完全不變（相容性測試）

**不要做**：不要在這一項引入求解器。不要改 `decide()` 的權威順序。

---

### W6 — 邊緣 fail-safe 與停電偵測

**現況**：控制鏈是 雲端 → MQTT → 設備，沒有邊緣自治。
文件誠實地寫了「策略跑在排程器週期，不是毫秒級 PCS 迴路」——這個邊界對套利是對的，
但有三個場景撐不住。

**問題**：

1. **斷網時電池停在最後一個設定點。** 如果那是「放電 500 kW」而網路斷了兩小時，
   SOC 會被放乾。
2. **停電偵測「尚未實作」**（文件自列）。備援是五大用途之一，
   停電時會發生什麼目前沒有被定義也沒有被測試。`backup_only` 只是把 SOC 維持住。
3. 秒級需量控制（見 W2）。

**要做什麼**：

**(a) 設定點加有效期。** 擴充 `set_power_setpoint` 的參數：

```json
{ "power_w": -200000, "valid_until": "2026-08-23T10:15:00Z", "on_expiry": "idle" }
```

設備／邊緣在 `valid_until` 過期後自行降級（`idle` = 歸零，
`hold` = 維持，`reserve` = 充到備援水位）。這是最小改動、最大保護的一步。
協定文件與 `device-protocol` 要同步更新，模擬器要實作它。

**(b) 停電偵測。** 不要用「有柴發輸出」當近似（文件已經點名這是錯的）。
判準建議：關口電表電壓 metric 掉到門檻以下 **且** 持續 N 秒
（沿用告警引擎的 `for_duration` 語意）。偵測到之後：
- 發出 `DeviceEvent` 與告警
- 該場域的節費記 `null`（既有規則）
- 調度策略切換到備援模式，且**這個切換要能在斷網時由邊緣自己完成**

**(c) 心跳與 watchdog。** 雲端定期發心跳；邊緣連續 N 次未收到就進入
本地降級策略。降級行為要寫在 `StoragePlan` 上而不是寫死。

**驗收**：
- 模擬器實作 `valid_until`，e2e 測試：下一個 60 秒有效期的設定點，
  斷開雲端，驗證 61 秒後電池歸零
- 停電情境測試：電壓掉 → 事件 + 告警 + 節費記 null
- 斷網 30 分鐘後恢復，SOC 沒有被放乾

**不要做**：這一項不要碰 `dispatch_command()` 的閘門邏輯。
不要引入新的通訊通道——沿用既有 MQTT 與命令機制。

---

## 4. 附錄：小項清單

不急，但都是真實缺口，可以夾在大項之間清掉：

- `DispatchWindow.recurrence` 欄位存在但引擎不展開重複規則，每日排程要手動建
- `Metric.counter_max` 內建目錄尚未填值
- 台電電價模型缺累進加價、基本費（每戶）、功率因數調整；
  契約容量只有單一值，沒有經常／非經常／半尖峰／離峰契約的分類
- SOH 估測與保固 throughput 追蹤（有日循環上限與 `battery_cycle` 成本，
  但沒有累計吞吐 vs 保固上限）
- 展示帳號密碼在版控裡（`ChangeMe-2026!`），對外前必須換
- 正式環境路徑：SQLite → PostgreSQL/TimescaleDB、SSE 輪詢 → Redis pub/sub + ASGI、
  MQTT mTLS 與憑證輪替、備份策略

**明確不在這個階段的範圍**：台電電力交易平台參與
（dReg / sReg / 補充備轉的投標、AFC 訊號、履約率追蹤、結算）。
那是最大的單一收入來源，但沒有 W1–W5 就去投標等於在賭。W6 之後再開。

---

## 5. 交付慣例

- **一次一個 PR，一個工作項目。** 不要合併。
- **每個 PR 附變更說明**：改了什麼、為什麼、哪些既有行為受影響。
- **既有測試全綠是最低門檻**，特別是 `tests/test_storage_strategies.py`、
  `tests/test_demand_benefit.py`、`scripts/verify_calculations.py`。
- **新邏輯要有測試釘住失效模式**，不只是快樂路徑。
  參考 `test_a_charging_battery_does_not_look_like_an_excursion` 的寫法——
  測試名稱直接說明它在防什麼。
- **降級行為要明確寫出來**：預測失敗、讀值缺失、涵蓋率不足、
  電池不回應時各自怎麼辦，不能靠預設行為。
- 動到既有設計決定時，同步更新 `docs/system-logic.html`
  （那份是「現在是什麼樣」）與 `docs/release-notes.html`。
- 註解用繁體中文寫「為什麼」，識別名用英文，沿用既有 docstring 的語氣。
