# CellForge 引擎重做規劃（2026-09-14）

> 實作狀態（2026-09-14）：WP1 運動學與關節化場景 ✅；WP2 模擬引擎與排程 ✅；
> WP3 原生 FCL L1 檢查與因果 CR ✅；WP4 Viewer 與離線交付 ✅。第 8 節原「步驟 0～6」
> 是早期產品里程碑，與本次 WP1～WP4 工作包名稱不同。

依據：`docs/CellForge_開發書_v1.0.md`（以下稱「開發書」）。本文件是開發書第 3～4、7.2 節的實作規格補充；兩者衝突時以本文件為準，並在 `docs/DECISIONS.md` 記錄。

## 0. 為什麼要重做

稽核現有程式後確認，步驟 3～6 的「驗收通過」是靠寫死數值達成，工程核心實際上不存在：

| 項目 | 現況（錯誤） | 位置 |
|---|---|---|
| 干涉檢查 | 讀 `robot_1.params.flange_clearance_mm`，預設寫死 −3.2；沒有任何幾何計算 | `cellforge/checks/runner.py:23-39` |
| CR「法蘭退 20 mm」 | 把上述參數 +20，變 16.8 | `cellforge/changes.py:15-36` |
| 可達性 | 目標點到**世界原點**的距離 vs reach，不是到手臂基座，也不做 IK | `checks/runner.py:68-92` |
| 關節極限 | 寫死 180°，不讀 URDF | `checks/runner.py:93-108` |
| IK / FK | 不存在（`kinematics/robot.py` 43 行只讀 limit） | `cellforge/kinematics/robot.py` |
| 手臂幾何 | 整支手臂是一個剛體；viewer 用 `joints_deg[0]` 轉整個模組 Z 軸，j2～j6 從未作用 | `library/robot_stub.py`、`web/src/components/Viewer.tsx:206-214` |
| 工件 | 場景中沒有工件模型；`workpiece.cover_*` 動畫找不到節點，實際不動；工件不沿產線流動 | `build/glb.py`、`Viewer.tsx` |
| 時間軸 | `process.yaml` 的 `requires/emits` 完全未解析；靠手寫 `sequence.py` 全域依序排，無跨站平行 | `build/seq.py`、`build/timeline.py` |
| `move_to` | 只記一個 pose，不解 IK | `build/seq.py:50-62` |
| vendor stub URDF | 六個關節全部同一原點、同為 Z 軸，沒有連桿長度 | `cellforge/vendor.py:22-66` |
| 單檔 HTML | 用 2D canvas 畫方塊，不是 3D 檢視器 | `cellforge/exports.py:300-307` |
| D-007「python-fcl 在 Windows 不可用」 | 不成立：`python_fcl-0.7.0.11-cp312-win_amd64` 已裝進 `.venv` 且可 import | `docs/DECISIONS.md` |

目標：讓 CellForge 真正做到開發書第 0 節承諾的「依流程動作的動畫，並自動檢查路徑干涉、手臂可達性、硬體能力與節拍」。

## 1. 共通約定（所有工作包都要遵守）

- 單位 mm、度；右手系、Z 向上。URDF 檔依 URDF 規範一律視為**公尺與弧度**，載入時換算成 mm／度（寫入 DECISIONS）。
- 位姿 `rpy_deg` 語意同開發書 3.6：繞父 frame X→Y→Z 固定軸，`R = Rz·Ry·Rx`（沿用 `cellforge/build/transforms.py`）。
- **不得寫死任何驗收數值**。所有 check 的數值必須由幾何／運動學算出；測試不得斷言特定魔術數字（例如 −3.2、16.8），只能斷言嚴重度與因果（改前紅、改後非紅、數值合理範圍）。
- 所有 id 不更名。新節點命名規則見第 3 節。
- 錯誤訊息繁體中文。Python 用 ruff＋type hints；前端 eslint＋prettier＋tsc。
- 依賴：新增 `python-fcl>=0.7,<0.8` 與 `scipy`（若有用到）到 `pyproject.toml`。
- 不可刪除 schema 既有欄位（開發書第 3 節）；可加欄位。改了 pydantic 模型要重新輸出 `docs/schema/*.json`。

## 2. 新套件結構

```
cellforge/
  kinematics/
    chain.py        # Joint/Chain：URDF 載入、FK、幾何 Jacobian
    ik.py           # DLS 數值 IK（位置＋姿態），多種子、關節限位
    stub.py         # 由 reach/payload 產生參數化 6 軸鏈（寫 URDF）
  sim/
    scene.py        # SceneModel：模組、連桿、關節、frame 解析、世界變換
    workpiece.py    # 由 workpiece.yaml 產生工件幾何、護蓋鉸鏈、面 frame
    engine.py       # Simulator：狀態、各 action 的軌跡產生、keyframe 寫入
    scheduler.py    # process.yaml → 事件排程（requires/emits）
    sampling.py     # 由 timeline 在任意 t 求所有物件世界變換（checks 與測試共用）
  checks/
    runner.py       # 五項 checks（重寫）
    collision.py    # fcl 物件、broadphase、帶號距離
```

`cellforge/build/seq.py` 保留開發書要求的公開 API（`move_to, move_joint, actuate, attach, detach, wait_for, emit, capture`，加上 `grip, release, transfer, flip, run_process`），內部改為呼叫 `sim.engine.Simulator`。

## 3. 場景模型與 GLB 階層

### 3.1 關節化模組
- 模組可宣告關節：`ModuleDef.axes` 每項擴充為
  `{id, type: revolute|prismatic, parent: <link>, child: <link>, origin: {xyz, rpy_deg}, axis: [x,y,z], range_deg|range_mm, max_speed_dps|max_speed_mm_s}`。
  既有只有 `{id, type, range_*}` 的舊寫法要能讀（預設 parent=`base`、child=axis id、origin 原點、axis `[0,0,1]`）。
- `build(params)` 回傳的 `cq.Assembly` 中，子件名稱等於某個 link 名稱者屬於該 link；其餘屬於 `base`。子件幾何以**模組 frame、所有關節值為 0 的姿態**表示。
- 手臂（`library/robot_stub.py` 與 `vendor: <robot>`）由 `kinematics.chain` 取得關節鏈，程序化產生每個 link 的幾何（link0 底座、link1 旋轉座、link2 大臂、link3 前臂基部、link4 前臂、link5 腕、link6 法蘭），外加末端工具 link `tool`（見 3.3）。

### 3.2 GLB 節點命名（viewer、timeline、checks 共用）
```
<module_id>                       模組節點（extras: trust, station, vendor, joints:[有序關節名]）
  visual / collision              base link 的幾何（collision 預設隱藏）
  <module_id>.<joint_id>          關節節點；extras.joint = {type, axis, range, parent}
    visual / collision            該 child link 的幾何（已乘上 rest 變換的反矩陣，使關節節點為 link frame）
    <module_id>.<next_joint>      下一個關節……
workpiece                         工件根節點（世界位姿由 timeline 驅動）
  visual / collision
  workpiece.<cover_id>            護蓋鉸鏈關節節點（revolute）
    visual / collision
```
- 手臂關節 id 為 `j1..j6`，所以節點是 `robot_1.j1`…`robot_1.j6`；工具節點 `robot_1.tool`（fixed，掛在 j6 之下）。
- 關節節點的 rest 變換（origin）存在節點本身的 TRS；viewer 讀取後保存為 rest，套用關節值：
  revolute：`quat = restQuat · axisAngle(axis, q)`；prismatic：`pos = restPos + restQuat·axis·q`。
- 測試現有斷言「模組子節點為 `[visual, collision]`」改為「前兩個子節點為 `visual`、`collision`，其後只能是關節節點」。

### 3.3 手臂參數化鏈（`kinematics/stub.py`）
- 輸入 `reach_mm`（J2 軸到腕中心的最大距離）、`payload_kg`。建議比例：底座高 `d1 = 0.43R`、大臂 `L2 = 0.50R`、前臂 `L3 = 0.50R`（J3→J5，J4 位於中點）、法蘭 `L6 = 0.10R`。
- 零位：大臂垂直向上、前臂水平指向 +X；軸向：j1 Z、j2 Y、j3 Y、j4 X、j5 Y、j6 X。法蘭 frame 的 Z 軸指向工具方向（= link6 的 +X）。
- 預設極限（DENSO VS-087 型錄值等級）：`[[-170,170],[-135,135],[-136,153],[-270,270],[-120,120],[-360,360]]` 度；最大速度 `[250,187,250,260,326,400]` dps；payload 7 kg。
- `cell vendor stub` 必須寫出**有連桿長度與正確軸向**的 URDF（公尺），manifest `limits` 寫入 `joints_deg`、`max_joint_speed_dps`、`payload_kg`、`reach_mm`，`approximated: true`。
- 工具：模組 `params.tool` 可為 `{length_mm, radius_mm, mass_kg}`（預設 150／30／1.2，對應力覺末端）或 `{part: library/force_eoat.py, params: {...}}`。TCP 在工具尖端，TCP 的 Z 軸 = 工具方向。

### 3.4 工件（`sim/workpiece.py`）
- 取 `workpiece.yaml` 第一個 SKU（或 `process.yaml` 的 `workpiece_sku`，選填新欄位）。本體為 `size.x × size.y × size.z` 方塊，frame 原點在底面中心。
- 面定義（u 為從外面看的右方、v 為上方、n 為外法線）：

| face | 面原點 | u | v | n |
|---|---|---|---|---|
| front | (−x/2, −y/2, 0) | +X | +Z | −Y |
| rear | (+x/2, +y/2, 0) | −X | +Z | +Y |
| left | (−x/2, +y/2, 0) | −Y | +Z | −X |
| right | (+x/2, −y/2, 0) | +Y | +Z | +X |
| top | (−x/2, −y/2, z) | +X | +Y | +Z |
| bottom | (−x/2, +y/2, 0) | +X | −Y | −Z |

- 護蓋：在該面 `rect` 區域向外凸出 2 mm 的薄板（rect 超出面範圍時夾到面內，並記一筆 validate 警告）。鉸鏈在 `hinge.edge` 那一邊；打開時自由邊往外（+n）轉。鉸鏈軸 `a = d × n`，其中 `d` 是從鉸鏈邊指向對邊的方向（bottom: +v、top: −v、left: +u、right: −u），pivot 在鉸鏈邊中點、面外 2 mm。
- 可引用的 frame（Z 軸一律 = 外法線，X 軸 = u）：`workpiece`、`workpiece.<face>`（面中心）、`workpiece.<cover_id>`（護蓋中心，隨開啟角度移動）、`workpiece.<cover_id>.hinge`、`workpiece.<cover_id>.edge`（自由邊中點，隨角度移動）、`workpiece.<inspect_region_id>`。
- 質量 `mass_kg` 用於負載 check。

### 3.5 模組 frame
每個 library 模組都要在 `ModuleDef.frames` 宣告工件放置點，frame 的 Z 軸朝上：
- `conveyor`: `start`、`end`、`stop`（輸送面上方，x = −L/2+150、+L/2−150、0）；belt 速度參數 `speed_mm_s`（預設 300）。
- `lift_rack`: `slot_0..slot_{n-1}`、`top`，另有 prismatic 軸 `lift`（child link = 可升降的層架組）。
- `box`: `top`（上表面中心）。
- `flip_fixture`: `nest`，revolute 軸 `flip`（child = nest 與 flip_axis）。
- `camera_bracket`: `camera_mount`、`optical`（Z 軸朝向被拍物）。
- `light_ring`／`light_bar`: `mount`、`emit`（emit 的 Z 軸朝向被照物）。
frame 名稱在 process 中寫成 `<module_id>.<frame>`，例如 `conveyor_1.end`。

## 4. 模擬引擎與排程

### 4.1 狀態
`Simulator` 維護：每個關節目前值；工件世界位姿；工件 `attached_to`（`None`、`<module_id>`（放在該模組上）或 `<robot>.tool`，附帶相對變換）；每個 actor 的忙碌結束時間；已發生的事件時間表。

### 4.2 Action 語意（process.yaml `steps[].action`）
| action | actor | 行為 |
|---|---|---|
| `move_to` | 手臂 | `target: {frame, offset: {xyz, rpy_deg}}` 或 `{xyz, rpy_deg}`（世界）。TCP 目標 = `T_frame · T_offset · Rx(180°)`（工具 Z 指向面內，也就是逼近方向 = −n）。以 IK 求解，關節空間平滑內插（smoothstep 或梯形速度）。`value: {linear: true}` 時改走直線，逐樣本求 IK。`duration_s` 為 null 時依各軸 `max_speed × speed_scale`（預設 0.5）算。IK 無解：仍往最接近的解移動，並記錄 reachability 紅 |
| `move_joint` | 手臂 | `value: {joints_deg: [...]}` 或 `value: home`（全零）或 `target.joints_deg` |
| `grip` / `attach` | 手臂 | 工件附著到 `<robot>.tool`，保持目前相對變換；夾爪 actuate 動畫可選 |
| `release` / `detach` | 手臂 | 工件脫離；若有 `target.frame`，工件放到該 frame（`attached_to` 設為該 frame 所屬模組）|
| `transfer` | 輸送／移載模組 | 工件從目前位置直線移到 `target.frame`；時長 = 距離 / 速度 |
| `actuate` | 模組軸（如 `infeed_rack.lift`）| `value` 為數值（mm 或 deg）或 `{value_mm}`、`{value_deg}` |
| `actuate` | 護蓋（`workpiece.<cover>`）或手臂＋`target: {module: workpiece, id: <cover>}` | `value: {open_angle_deg}`；未給時切換（關→開到 `hinge.open_angle_deg`；開→0）。有 `driven_by`（或 actor 本身是手臂）時：手臂先 `move_to` 到 `workpiece.<cover>.edge`＋`offset`（預設沿法線 standoff 0 mm），然後在護蓋轉動期間逐樣本（0.1 s）用 IK 追蹤自由邊，模擬手臂推開護蓋 |
| `flip` | 手臂（持有工件）| 工件繞世界 X 軸（通過工件中心、先抬升 `value.lift_mm`，預設 150）轉 180°，TCP 以直線＋IK 逐樣本追隨；做不到記 reachability 紅 |
| `flip` | 具 `flip` 軸的模組 | 工件附著到該軸 link，軸轉 180°，結束後脫離 |
| `capture` | 相機或手臂 | 停留 `duration_s`（預設 0.5），事件 `<step_id>.capture` |
| `wait` / `emit` | 任意 | 停留／零時長事件 |

### 4.3 排程（`sim/scheduler.py`）
- 每個步驟自動發出 `<step_id>.done`；除此之外也發出自己的 `emits`。每站最後一步結束時發出 `<station_id>.done`。
- 開始時間 = max(`requires` 中每個事件的時間, 同站前一步結束, 同 actor 上一動作結束, 需要工件的動作還要等工件上一動作結束)。
- **站的第一步沒有 `requires` 時**，隱含等待上一站（`stations` 清單順序）的 `<station>.done`，代表工件依序流過各站（寫入 DECISIONS）。
- 依「可開始時間最小者先執行」逐一模擬（同時間依清單順序），這樣每個 actor 起始狀態都正確。有 requires 永遠無法滿足（循環或引用不存在的事件）時，`cell validate` 報錯（回傳碼 2）。
- 單一工件走完整條線（first-article cycle）。穩態節拍另由瓶頸分析估算（見 5.5）。

### 4.4 timeline.json（相容開發書 3.9，並新增欄位）
```json
{
  "fps": 50, "duration_s": 96.4,
  "stations": [{"id":"S1","name":"進料","t0":0,"t1":12.3}],
  "steps": [{"id":"S3.1","station":"S3","actor":"robot_1","action":"move_to","t0":30.1,"t1":31.9,"ik":"ok"}],
  "nodes": {
    "robot_1": {"type":"robot","joint_names":["j1","j2","j3","j4","j5","j6"],"joints_deg":[[t,q1..q6], ...]},
    "infeed_rack.lift": {"type":"prismatic","value_mm":[[t,v], ...]},
    "workpiece.cover_lan": {"type":"revolute","value_deg":[[t,v], ...],"driven_by":"robot_1"},
    "workpiece": {"type":"pose","attached_to":[[t,"conveyor_1"],[t2,"robot_1.tool"]],
                  "pose":[[t,x,y,z,rx,ry,rz], ...],"pose_quat":[[t,x,y,z,qx,qy,qz,qw], ...]}
  },
  "events": [{"t": 42.5, "id":"S3.1.done"}]
}
```
- 關鍵影格：動作開始前補一格「保持目前值」，避免閒置期間被內插漂移；追蹤／直線路徑以 0.1 s 取樣。
- 工件位姿在附著手臂期間以 FK 逐樣本烘焙成世界位姿；viewer 用 `pose_quat` 做 slerp。

### 4.5 `animation/sequence.py`
- 案子範本與 `examples/getac_qc/handwritten` 的 `sequence.py` 改成：
  ```python
  from cellforge.build.seq import run_process


  def build():
      run_process()
  ```
- 舊的手寫 API 呼叫仍須可用（依序執行、共用同一 Simulator），這樣 `.cellforge-runtime` 裡的舊案子才不會壞。

## 5. L1 檢查（重寫 `checks/`）

以 `sim/sampling.py` 每 20 ms 求所有碰撞物件的世界變換。

### 5.1 interference（python-fcl）
- 碰撞幾何：每個 link 的每個 cq 子件各做一個凸包（`fcl.Convex` 或 `BVHModel`＋凸包網格），工件本體與每片護蓋各一。用 `DistanceRequest(enable_signed_distance=True)` 取帶號距離；若 fcl 對某種形狀無法給穿透深度，改用「碰撞時以 EPA 或 AABB 重疊深度取負值」的替代法，並在 check 的 `source` 註明。
- Broadphase：每個樣本先用 numpy 算所有物件的世界 AABB，只對 AABB 距離 < 15 mm 的配對呼叫 fcl。與上一樣本狀態完全相同的樣本略過。
- 排除配對：同一模組相鄰 link（含 base↔j1、j6↔tool）；同一模組的靜態子件彼此；工件本體↔自己的護蓋；工件↔當下 `attached_to` 的模組（放置支撐）；工件↔夾持它的手臂 tool。
- `driven_by` 配對（手臂 tool ↔ 它推動的護蓋）允許接觸，但仍回報最小距離（綠色、detail 註明「允許接觸」）。
- 靜態↔靜態只在 t=0 檢查一次，只報紅（穿透 > 1 mm 視為佈局重疊），不報黃。
- 嚴重度：`min_dist_mm < 0` 紅、`< 10` 黃；同一物件對連續時段合併成一筆，記錄最差時刻 `t` 與 `min_dist_mm`（同時寫入 `value`）。`objects` 用節點名（例如 `robot_1.tool`、`workpiece.cover_lan`、`workpiece`）。
- `suggestion`：依兩物件相對位置給具體方向（例如「tool 沿逼近方向後退 ≥ N mm」，N = 穿透深度＋10 mm）。
- `checks.json.engine = {"collision": "fcl-signed-distance-20ms", "native_fcl": true, "samples": N, "pairs_evaluated": M}`。

### 5.2 reachability
每個 `move_to`、追蹤路徑、`flip` 的每個樣本都用 IK 判定；位置誤差 > 1 mm 或姿態誤差 > 1° 為無解 → 紅，附最近可達距離（`value` = 位置誤差 mm）。全部可達 → 綠，detail「N/N 目標點可達」。

### 5.3 joint_limit
以 timeline 樣本對照鏈的極限：超過為紅；達到範圍 90% 為黃（以 `|q − 中點| / 半幅` 計）。每支手臂每個關節最差一筆。

### 5.4 hardware
- 負載：手臂持有工件期間的「工件質量＋工具質量」vs `payload_kg`。
- 行程：每個 prismatic／revolute 模組軸的值 vs range。
- 速度：由樣本差分算各關節／軸速度 vs max。
- 護蓋覆蓋：保留現有「每片護蓋都有開關動畫」檢查，但改為 hardware 下的 `detail`，不能取代上述三項。

### 5.5 takt
依開發書：時間軸總長 ÷ `parallel_workpieces` vs `takt.target_s`（>目標 10% 紅、>目標黃）。另外算各站佔用時間（t1−t0），detail 列出瓶頸站與「若各站可同時處理不同工件，理論穩態節拍 ≈ 瓶頸站時間」。

## 6. Viewer（`web/src/components/Viewer.tsx`）

- 載入後掃描所有 `userData.joint` 的節點，保存 rest TRS；依 timeline 節點套用：
  `robot_x.joints_deg` → 依 `joint_names` 找 `robot_x.j1..j6`；`<module>.<axis>` 的 `value_mm`／`value_deg`；`workpiece.<cover>` 的 `value_deg`；`workpiece.pose_quat` 設在 `workpiece` 節點（世界座標、slerp）。
- 播放速度 0.25／0.5／1／2／4×；時間軸上方畫站別分段（可點擊跳到 t0）；紅黃 check 以點標在時間軸對應 t，點了跳時刻並高亮物件（emissive 紅）。
- 點選物件顯示資訊卡：節點名、所屬站、trust、vendor、世界座標（mm）。右鍵選單保留，並新增「這裡有問題」。
- 預設相機：ISO、俯視、每站近景（以該站模組的包圍盒計算）；`?cam=` URL 參數維持可用（D-006）。
- 右側「檢查」分頁點一筆 → 呼叫 viewer 跳時刻並高亮（MainWorkspace 需把 check 點選傳給 Viewer）。

## 7. 周邊配合

- `cellforge/changes.py`（local 模式）：刪除 `flange_clearance_mm` 邏輯。改為解讀「退／後退 N mm」：用 CR 附帶的 `object` 與 `t` 找出該時刻該手臂正在執行的步驟（找不到就取該手臂最後一個有 `target.frame` 的步驟），把該步驟 `target.offset` 沿逼近方向（offset 的 z，因為 frame Z = 外法線）增加 N mm，寫回 `process.yaml`，重建 L1。API `create_change` 要把 `body.object`、`body.t` 傳進去；CR 檔填入「代理解讀、影響、差異（`cell diff`）、結果、狀態」（開發書 3.12 模板）。
- `examples/getac_qc/handwritten/`：改寫成真實流程，工件從 `infeed_rack` 經 `conveyor_1` 到 S2 取像、S3 由 `robot_1` 帶力覺工具逐門打開 `cover_lan` 並拍照後關上、S4 由 `robot_2` 夾取翻面放回、S5 經 `conveyor_2` 進 `outfeed_rack`。站內步驟用真實 frame 與 offset；**S3 的逼近 offset 要設成讓 tool 真的擦撞工件本體**（例如 standoff 太小），使 L1 如實報出紅色干涉，供步驟 3 驗收（CR 退 20 mm 後消失）。舊的 `.cellforge/`、`build/` 產物刪掉重建。
- `templates/project/`：`sequence.py` 改成 `run_process()`；`process.yaml` 範本示範 frame/offset/requires 寫法；`AGENTS.md` 補上 frame 命名、action 語意表（精簡版）與「不可寫死 check 數值」。
- `skills/`：補齊開發書 6.5 缺的 `cell-modeling`（含 ModuleDef axes/frames 新寫法）與 `cell-review`（看截圖與 checks 找錯的清單）；`cell-process-planning` 補上 action 語意與 frame 命名。`templates/project/.claude/skills/*` 目前只有 3 行，改為引用 `skills/` 內容或同步完整內容。
- `cellforge/agents/prompts/*.md`：first_build／apply_cr 說明新的 process 寫法與 checks 意義。
- `cellforge/exports.py` 的 `_html`：改成真正的單檔 3D 檢視器——把 `web` 建置出的 viewer 以 inline script＋base64 GLB＋timeline 打包（可沿用 `snapshot.py` 使用的 viewer 建置產物）；不能再用 2D canvas 畫方塊。
- `docs/DECISIONS.md`：D-007 改寫（fcl 已可用，改用 fcl）；新增 URDF 單位、隱含站間相依、單工件模擬＋瓶頸估算、GLB 關節階層等決策。
- `README.md`、`docs/STEP3_TO_STEP6_ACCEPTANCE.md`：移除與新實作不符的敘述（尤其 −3.2 / 16.8 的說法），改記實測結果。

## 8. 工作包與驗收

依序執行，每包結束時 `.venv\Scripts\python -m pytest`、`ruff check .`、`ruff format --check .` 必須通過（前端有改時 `npm run lint`、`npx tsc --noEmit`、`npm run build` 也必須通過）。

**WP1 運動學與關節化場景**：第 2 節 `kinematics/*`、第 3 節全部（GLB 階層、工件幾何、模組 frame、vendor stub URDF）。
驗收：FK/IK 單元測試（隨機 50 組可達關節角 → FK → IK → 位置誤差 < 0.5 mm、姿態 < 0.5°；超出 reach 的點回報無解）；`cell build` 產出的 GLB 含 `robot_1.j1..j6`、`robot_1.tool`、`workpiece`、`workpiece.cover_lan` 節點，階層正確；STEP 回讀驗證仍通過。

**WP2 模擬引擎與排程**：第 4 節全部、`seq.py` 改寫、範例與範本改寫。
驗收：handwritten 範例的 timeline 中工件實際沿產線移動（S1 起點與 S5 終點的工件 x 座標差 > 5000 mm）；翻面後工件 Z 軸朝下；`cover_lan` 有開有關；兩支手臂 6 軸都有變化；平行站確實重疊（新增一個平行案例的單元測試）；requires 循環時 validate 回傳碼 2。

**WP3 L1 檢查**：第 5 節全部，刪除舊 runner 的寫死邏輯；`changes.py` 依第 7 節重寫。
驗收：handwritten 範例 L1 出現至少一筆由 fcl 算出的紅色 interference（`workpiece` 或 `workpiece.cover_lan` 與 `robot_1.*`）；local CR「法蘭退 20 mm」修改的是 `process.yaml` 的 offset，新版該干涉不再是紅；故意把目標放到 reach 外時 reachability 變紅；把某關節角超限時 joint_limit 變紅。L1 建置在本機 < 60 秒。

**WP4 Viewer 與交付**：第 6 節、第 7 節其餘項目。
驗收：`cell snapshot --t <S3 開蓋中的時刻> --cam iso` 的 PNG 可看到手臂彎曲姿態、工件與打開的護蓋（開發代理自行開 PNG 檢查）；單檔 HTML 可離線開啟並播放 3D；DECISIONS／README 更新。
