---
name: cell-modeling
description: 建立或修訂 CadQuery 關節模組與 frame-based CellForge 產線幾何，包含可重用機構與機器人整合。
---

# CellForge 模組建模

把 `cell.yaml`、`workpiece.yaml`、`parts/`、`library/` 與 vendor manifest 視為工程真相。
所有 id 保持穩定；單位為 mm、角度為度，使用右手座標系且 Z 向上。推估的位姿與尺寸標成
`trust: inferred`，沒有證據不得升成 confirmed。

## 建模來源判定樹

必須依序判定，不可直接拿方塊頂替：

1. 執行 `cell part list` 查 `library/manifest.yaml`；若有適用模組，只調參數。
2. 沒有時判定來源。六軸手臂、夾爪／吸盤、工業相機／鏡頭、線性模組／電缸、氣缸、
   伺服馬達／減速機與光源本體屬 Tier V；先用 `cell vendor add`，取不到才用
   `cell vendor stub`，且型錄 reach、payload、包絡、法蘭、limits 必須填真值。
3. 鋁擠框架、輸送段、治具、支架、圍籬／門、電控箱、作業桌、料倉、翻面機構、
   遮光罩與警示燈柱屬 Tier P。庫內沒有時，用
   `cell part new <id> --category <category> --project .` 在案內 `parts/` 自建。
4. 將選型與所有推估寫入 `analysis/assumptions.yaml`，尺寸來源寫入 `meta.basis`。

## 十項品質標準與做法

1. 尺寸依據：`ModuleDef.meta.basis` 寫明型錄、實測、工程圖或工程推估的來源，不保留
   `TODO：填寫尺寸依據`。
2. 安裝介面：畫出底板與孔位、T 槽、法蘭或支撐腳，讓四視圖能判斷機構確實裝得上。
3. 具名子零件：每個 assembly child 用功能、方位或層序命名，如 `post_fl`、
   `shelf_3`、`lens_barrel`，不要用執行期計數或 `solid1`。
4. Frames：至少提供 `mount` 與必要工作點；把 frame 放在真實介面／機構學位置，
   可動 frame 以 `link` 綁定正確子連結，只有真正的空間工作點才用 `free_space`。
5. Axes：可動機構提供非零 range、正確 parent／child、局部軸向與真實量級 max speed，
   並在預覽裡走完整行程確認旋轉中心或滑移方向。
6. Collision：選用 `box`／`hull`／`mesh`，框架與鏤空機構拆成逐桿件子零件，
   不用一個外盒吞掉開放空間。
7. 配色：每個子零件明確指定符合工程慣例的 `cq.Color`，用色彩區分結構、動件與介面。
8. 參數：提供有效 draft 2020-12 JSON Schema；每個數值參數有合理 minimum／maximum，
   且單獨拉到兩端都能成功 build。
9. 三角形數：用能辨識型式的簡化幾何，避免螺紋與裝飾細節，使 visual 網格維持在
   `cell part check` 的三角形預算內。
10. 落地：落地模組幾何最低點碰到 z=0；被承載者在 `cell.yaml` 宣告
    `mount: <module_id>[.<frame>]`，但 world pose 仍由自己的 `pose` 唯一決定。

## ModuleDef 與運動語意

Python 模組匯出 `build(params) -> cq.Assembly` 及 `MODULE: ModuleDef`，需要動態 frames
或 axis range 時再加 `module_definition(params)`。每個 CadQuery 子零件都要命名與上色。
可重用 frame 例如 `frames={"mount": Frame(...), "top": Frame(...)}`。

`ModuleInstance.pose` 永遠是世界 pose。被其他模組承載時，`mount` 只是供 validation
判定支撐的宣告，不會 re-parent，也不會改寫世界 pose。引用的模組與 frame 必須存在。

可動機構以 `ModuleDef.axes` 宣告，例如：

```python
ModuleAxis(
    id="lift",
    type="prismatic",
    parent="base",
    child="lift",
    origin=JointOrigin(xyz=(0, 0, 0), rpy_deg=(0, 0, 0)),
    axis=(0, 0, 1),
    range_mm=(0, 480),
    max_speed_mm_s=200,
)
```

旋轉軸使用 `range_deg` 與程式實際欄位 `max_speed_dps`。axis 向量位於 joint 的局部
frame。child link 的幾何必須直接畫在模組零位時的世界位置；GLB exporter 會乘 rest
transform 的反矩陣換回 joint-local。以 `assembly.add(..., metadata={"link": "door"})`
指定 link，並用 `Frame(..., link="door")` 把可動 frame 掛上去。

優先重用 library 的輸送機、升降料架、治具、翻面機、相機／光源支架、力覺工具、鋁擠
機架與安全圍籬。Vendor 元件應用可追溯 URDF／STEP；只有取不到時才做 approximated
stub，而且必須使用真實關鍵尺寸、軸限位、速度、reach 與 payload。

## 完整範例一：`extrusion_frame` 靜態鋁擠機架

這是「看得出型式、不畫製造細節」的基準。方形擠型只保留四面淺槽與中心孔，不畫完整
T 槽與螺絲。

| 參數 | 預設 | 範圍 |
|---|---:|---|
| `size_mm` | `[1200, 800, 1800]` | 每軸 200～6000 |
| `profile_mm` | 40 | 30／40／45／60 |
| `posts` | 4 | 4／6 |
| `beam_levels_mm` | `[80, 1800]` | 0～size_z |
| `with_feet` | true | 布林值 |

建置時在外廓角落加入 `post_fl`、`post_fr`、`post_rl`、`post_rr`；六柱時加
`post_ml`、`post_mr`。每層建立 `beam_<lvl>_front/rear/left/right`，每個交界建立
`bracket_<post>_<lvl>`，並依方位建立 `foot_fl` 等地腳。每根桿件都是獨立 assembly
child，因此 `collision="box"` 產生逐桿件碰撞盒，框內保持開放。

動態定義必須依參數產生：

```python
frames = {
    "mount": Frame(xyz=(0, 0, 0), free_space=True),
    "top_front": Frame(xyz=(0, -width / 2, height)),
    "top_rear": Frame(xyz=(0, width / 2, height)),
    "top_left": Frame(xyz=(-length / 2, 0, height)),
    "top_right": Frame(xyz=(length / 2, 0, height)),
    "inner_center": Frame(xyz=(0, 0, height / 2), free_space=True),
}
for level in beam_levels:
    frames[f"rail_{level:g}_front"] = Frame(xyz=(0, -y_edge, level))
    frames[f"rail_{level:g}_rear"] = Frame(xyz=(0, y_edge, level))
    frames[f"rail_{level:g}_left"] = Frame(xyz=(-x_edge, 0, level))
    frames[f"rail_{level:g}_right"] = Frame(xyz=(x_edge, 0, level))
return ModuleDef(
    id="extrusion_frame",
    params_schema=params_schema,
    frames=frames,
    collision="box",
    meta=ModuleMeta(basis="依 40×40 鋁擠型材標準斷面與一般設備機架尺寸，斷面簡化為方廓加四面淺槽"),
)
```

鋁擠用 `Color(0.72, 0.74, 0.76)`、角件用 `Color(0.35, 0.37, 0.40)`、地腳用黑色。
目標三角形預算約 12,000；完成後預覽碰撞體，必須看到每根立柱與橫樑各自的盒，而不是
包住整框的一只大盒。

## 完整範例二：`safety_door` 可動安全門

| 參數 | 預設 | 範圍 |
|---|---:|---|
| `width_mm` | 900 | 400～1500 |
| `height_mm` | 1800 | 800～2500 |
| `hinge_side` | `left` | left／right |
| `profile_mm` | 30 | 30／40 |
| `open_angle_deg` | 110 | 60～170 |

base link 包含 `frame_post_hinge`、`frame_post_latch`、`hinge_upper`、
`hinge_lower`；door link 包含 `door_stile_hinge`、`door_stile_latch`、
`door_rail_top`、`door_rail_bottom`、2 mm 的 `door_mesh` 與 `door_handle`。
所有 door 子零件都在門關閉時的實際世界位置直接建模，絕不先移到鉸鏈原點：

```python
assembly.add(
    door_stile_hinge, name="door_stile_hinge", color=SAFETY_YELLOW, metadata={"link": "door"}
)
assembly.add(
    door_stile_latch, name="door_stile_latch", color=SAFETY_YELLOW, metadata={"link": "door"}
)
assembly.add(door_mesh, name="door_mesh", color=MESH_GREY, metadata={"link": "door"})
axis = ModuleAxis(
    id="swing",
    type="revolute",
    parent="base",
    child="door",
    origin=JointOrigin(xyz=(hinge_x, 0, 0)),
    axis=(0, 0, 1),
    range_deg=(0, open_angle_deg),
    max_speed_dps=90,
)
frames = {
    "mount": Frame(xyz=(hinge_x, 0, 0), link="base"),
    "hinge": Frame(xyz=(hinge_x, 0, height / 2), link="base"),
    "latch": Frame(xyz=(latch_x, 0, handle_z), link="door"),
}
```

門框與門扇用安全黃 `Color(0.95, 0.75, 0.10)`，網片用半透明深灰，門把與鉸鏈用
金屬灰。`collision="box"` 的碰撞子件跟著各自 link；門扇保持鏤空可辨識。目標三角形
預算約 3,000～5,000。預覽把 swing 從 0 拉到 `open_angle_deg`：鉸鏈側必須留在原地，
latch 端以門寬為半徑掃弧；若整扇門飛離，表示零位世界幾何或 link 指派錯誤。

## 常見錯誤

- Frame 浮在空中：把一般安裝／工作 frame 放回實體表面或正確機構點；不可濫用
  `free_space` 逃避檢查。
- 碰撞 hull／box 吞掉鏤空：把柱、樑、層板拆成具名子零件，逐件產生碰撞體。
- 子零件名稱無意義：改用功能、方位與層序；避免 `solid1` 與會隨迴圈變動的計數名稱。
- 可動件寫在錯誤 link：幾何用 `metadata.link`、frame 用 `Frame.link` 綁同一 child。
- 落地模組沒有碰 z=0：量測整體最低點並修正幾何，不要只移 mount frame。
- 參數沒有上下限：為每個數值欄位補 minimum／maximum，逐項測兩端 build。

完成後執行 `cell part check <id> --project . --json` 與
`cell validate --project . --json`，再建置 L1、檢查 OCP STEP 名稱保留，並在有意義的
運動時間產生 ISO 與站別截圖。不得直接編輯 `build/` 或 `.cellforge/vN`。
