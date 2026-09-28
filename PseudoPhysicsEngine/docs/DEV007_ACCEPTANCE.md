# DEV-007 廠商模型與鏈驗收紀錄（ACC-03）

日期：2026-09-28
依據：`docs/CellForge_平台擴充開發書_v2.0.md` P1、DEV-007、ACC-03；決策 D-036。
方法：同一 Getac 配置（`examples/getac_qc/handwritten` 建案），只把 `robot_1` 從 `library/robot_stub.py` 換成 DENSO 公開的 VS-060 URDF，`robot_2` 保留近似 stub。建置與回讀都走 `cell build`／`cell version verify`；一致性由驗收腳本在時間軸上取樣量測，所有數值都是量測結果，不是驗收常數。

## 1. 結論

- **ACC-03 通過。** robot_1 關節移動時，viewer 語意下的 GLB 節點、取樣（`world_transforms`）、碰撞零件與 frame 都和運動鏈 FK 一致；robot_2 在建置警告、版本 manifest、GLB extras、檢查項目、前端檢查面板與報告中都標為近似廠商模型。
- 驗收中發現並修正 1 項缺陷：原廠鏈在 J6 與工具之間多了無外形的 `flange` 固定 link，碰撞相鄰判定因此把「工具裝在 J6 上」誤判為干涉（v1 的 CHK-INT-001 紅項，−0.020 mm）；修正後 v2 此項消失（D-036）。
- **工程檢查未通過**（v2：red 5、yellow 4、green 38），這是換成原廠模型後的真實結果，不是轉接錯誤：S3 取像點超出 VS-060 可達範圍（IK 失敗 21 點，集中在 S3.approach／open／close）、joint_3 峰值速度 172.586°/s 超過 URDF 限制 163.770°/s，以及沿用範例流程的節拍紅項。原本的 robot_stub 以 905 mm 臂展與較寬鬆的關節速度近似，這些問題因此被掩蓋。
- Getac 指定的 VS-087 沒有公開 URDF（DENSO 公開的 `denso_robot_ros/denso_robot_descriptions` 只有 `vs060_description`），因此 Getac 案維持近似 stub 並依本步驟標示；取得原廠檔後以 `cell vendor add-urdf` 登記即可替換。

## 2. 環境

| 項目 | 值 |
|---|---|
| 平台 | DEV-007 提交前的工作樹（即本提交內容） |
| 驗收案 | `.cellforge-runtime/projects/VS060_原廠URDF_ACC03_20260928`（v1：修正前、v2：修正後） |
| OS／Python | Windows 11 Home 10.0.26200／3.12.10；pycollada 0.9.3（讀 DAE） |

## 3. 原廠來源（2026-09-28 下載，逐檔 SHA-256 記於案內 `vendor/manifest.yaml`）

來源頁：<https://github.com/DENSORobot/denso_robot_ros/tree/master/denso_robot_descriptions/vs060_description>
授權：`package.xml`（denso_robot_descriptions 3.3.0）宣告 MIT。原廠檔只放在驗收案的 `vendor/` 內，不進平台 repo。

| 檔案 | SHA-256 | 三角面 |
|---|---|---|
| vs060.urdf | `1b5c80f4867ebea1070d278873a154524911a8542c12f353495ec20c31667ff8` | — |
| base_link.dae | `ff3053ef9c510d432fd8e13c1bb3562271cb0150e73d7137841db83f9eabd043` | 1055 |
| J1.dae | `5d3dc873816b6c0cf01c8942e8211b9926baefcb336167b315084ba82d12278b` | 1474 |
| J2.dae | `17eaeca6bb90e7f4e7c0ccb3567877388372063c39911e15e4f30b108c5d2299` | 2006 |
| J3.dae | `a1923fd8895482e6d7a7d2b2d4e063e0dcac34d7b82854fe8a620e668cc702a4` | 462 |
| J4.dae | `e77bf8373c54bf9040473170fd74f380506e85a00a0160d96dacbd4878564b49` | 1394 |
| J5.dae | `e4294d284838590c4755eb3ee31c5f1254404450d1c632a64ea116f5ccb57715` | 734 |
| J6.dae | `6b398a0572ce3a66d216b19de6e9385e4fddd6f66ee06972488fd962071f100d` | 186 |
| package.xml | `bbe571cf6b4ecc21ead2b1b21cf42413b25447f590e1089eb4ffb50d149de2d7` | — |

URDF 沒有法蘭或 `tool0` frame，也沒有負載資料。處置：法蘭暫定在 J6 原點（J6 網格 z 範圍 −20～0 mm，頂面即原點），vendor 條目的 flange 標 `trust: inferred`，並建立假設 `A-VS060-FLANGE`；法蘭偏移（`Q-VS060-FLANGE`）與額定負載（`Q-VS060-PAYLOAD`）列入 `analysis/questions.yaml`。manifest 不填 `payload_kg`，夾持時負載檢查會標「未評估」而不是判綠（本案 robot_1 不夾持工件）。

## 4. 建置與回讀

| 版本 | 建置 | 回讀驗證 | 工程檢查 | 建置警告 |
|---|---|---|---|---|
| v1（修正前） | L1，27.0 s | `cell version verify` 通過（6 產物、18 來源、6 庫模組、STEP 8 元件） | red 6／yellow 4／green 38 | robot_2 近似 stub 一則 |
| v2（修正後） | L1，28.2 s | 同上通過 | red 5／yellow 4／green 38 | robot_2 近似 stub 一則 |

運動鏈（URDF 公尺／弧度換算為 mm／度）：根 link `world`；活動關節 joint_1～joint_6 皆 revolute，限位與速度取自 URDF（例如 joint_1 ±170°、225°/s，joint_3 −125°～155°、163.77°/s）；固定關節 `joint_w`（URDF 原有）、`flange`、`tool`（TCP 沿法蘭 +Z 140 mm，取自 `library/force_eoat.py` 的 `tool_center_point`）。碰撞零件來自 URDF `<collision>`：base_link、J1～J6、tool。

## 5. ACC-03 一致性量測（v2）

取樣時刻取 robot_1 靜止（0 s）與 S3 大幅移動中（20、28、33、36.5 s）。關節值由時間軸內插（與前端 `viewer-core.ts` 相同語意：靜止姿態 × 關節運動），各項取五個時刻的最大值：

| 比對 | 最大差異 |
|---|---|
| GLB 節點世界變換（viewer 語意）vs FK（所有 link，含固定關節） | 1.7e-13 |
| 取樣 `world_transforms` vs FK | 0 |
| GLB visual 頂點 vs 原廠 DAE 網格依 FK 擺放（雙向最近點） | 1.5e-5 mm（float32 精度） |
| 碰撞零件凸包 vs URDF collision 網格依 FK 擺放的凸包 | 0 mm |
| `robot_1.flange` frame vs FK(J6)·法蘭偏移 | 0 |
| GLB `robot_1.tool` 節點 vs `robot_1.tool` frame | 1.7e-13 |
| tool 相對 flange | (0, 0, 140) mm，各時刻相同 |

關節值範例（33 s）：(−52.865, −81.147, 48.007, 65.167, 19.427, −7.119)°，TCP 世界座標 (286.00, 167.32, 819.54) mm。快照 `build/snapshot_t{0,20,33}_S3.png`、`snapshot_t33_iso.png` 目視確認各 link 網格在運動中保持連接、沒有脫離或錯位。

## 6. 近似 stub 標示（robot_2）

| 位置 | 結果 |
|---|---|
| 建置警告／render brief | 「模組 robot_2 為型錄尺寸近似（approximated stub，library/robot_stub.py）…」；robot_1 無此警告 |
| 版本 manifest `modules` | robot_1：`model_source=vendor-urdf:denso_vs060_urdf`、`approximated=false`；robot_2：`model_source=library`、`approximated=true` |
| GLB 模組節點 extras | 同上 |
| checks.json | 16 個涉及 robot_2 的項目帶 `approximated_models: ["robot_2"]`，`source` 附註「結果不代表原廠真機」；robot_1 的項目沒有 |
| 前端檢查面板 | 頂端顯示「ⓘ 近似廠商模型：robot_2 為型錄尺寸近似…」（`build/ui_checks_panel.png`） |
| 報告（v2 DOCX） | 「近似廠商模型（非原廠真機）：robot_2；…交付前需以原廠模型確認。」各檢查的 Evidence 行同步附註 |

## 7. v2 非綠項目（robot_1 相關為真實工程結果）

| 項目 | 嚴重度 | 內容 |
|---|---|---|
| CHK-REACH-001～003 | red | S3 取像點 112/122、25/31、26/31 可達，最差姿態誤差 2.918° |
| CHK-HW-003 | red | robot_1.joint_3 峰值速度 172.586／163.770 °/s |
| CHK-TAKT-001 | red | 有效節拍 59.53／45.00 s，瓶頸 S3（沿用範例流程） |
| CHK-INT-001 | yellow | robot_1.joint_5 ↔ robot_1.tool 7.500 mm |
| CHK-INT-002、004 | yellow | robot_1.tool ↔ workpiece 9.333、3.134 mm |
| CHK-INT-005 | yellow | robot_1.joint_4 ↔ robot_1.joint_6 3.327 mm |

## 8. 自動化測試

`tests/test_vendor_model.py` 以自製 URDF（混合 revolute／prismatic／固定關節、夾在中間的固定關節、無外形的 link、`package://` 與相對路徑、STL／OBJ、`<mesh scale>`、box／cylinder／網格碰撞）驗證同一套一致性，期望值由 URDF 原始數值以獨立 FK 推得；另含 SCARA（RRPR 四軸保持四軸、鉛直目標可解、傾斜目標誠實失敗）、只有 STEP 時為靜態模組且不能當 move actor、原廠檔被改動後驗證失敗、登記時缺網格被拒、近似標示、法蘭後方工具的相鄰判定、無額定負載時標未評估、只有近似條目才凍結 robot_stub。對 9 個關鍵實作逐一注入缺陷（取樣漏固定關節、URDF rpy 改成內旋、忽略 mesh scale、忽略 `<collision>`、碰撞與外形共用物件、丟掉法蘭偏移、prismatic 限位未換算、stub 旗標未傳遞、雜湊比對失效）以及相鄰判定修正，測試都會轉紅。
