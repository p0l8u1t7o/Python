# DEV-006 真實 Getac 代理驗收紀錄

日期：2026-09-28
依據：`docs/CellForge_平台擴充開發書_v2.0.md` DEV-006、ACC-02；`docs/CellForge_WP-A-C_規格_v1.2.md` 第 9 節。
方法：只透過 CellForge HTTP API 操作（建案、上傳、intake、略過問題、first_build），不人工修改任何工程資料；代理全程為正式 Claude Code 模式。

## 1. 結論

- **ACC-02 通過。** 正式代理 intake（job `466b6ece1c7a`）→ first_build（job `221d03581473`）在案 `軍規筆電_QC_線_P0驗收_20260928_05` 發布 v17：L1、`cell version verify` 回讀通過（manifest、雜湊、schema、GLB、OCP 重讀 STEP）、`agent_acceptance=true`、建置 34.9 秒。
- **工程檢查未通過**：v17 為 red 137、yellow 26、green 48，只能作為草案討論，不是工程驗收（D-034）。
- **缺模組自建（WP-A/C 第 4 項）通過。** 在隔離平台副本移除 `fixture_stand` 後，first_build（job `a4e5df03ccfd`）在 `parts/` 自建 `fixture_stand.py`，`cell part check` 0 fail／0 warn，正式共用庫未被修改。
- 驗收過程發現並修正 5 項平台缺陷（D-033～D-035），前 4 次 first_build 的失敗紀錄與日誌原樣保留。
- WP-A/C 第 9 節 14 項中：8 項通過（2、3、4、6、9、10、13、14），2 項未達成（1、5），第 7 項設備型式通過但發現懸空缺陷，3 項本輪未重新驗證（8 的前端互動、11、12）。

## 2. 環境

| 項目 | 值 |
|---|---|
| 平台 commit | `a70c75c`（run 5、run 6）；各次重跑對應的 commit 見第 4 節 |
| Claude Code | 2.1.283（VS Code 擴充套件內附執行檔，`detect_claude` 自 PATH 2.1.266 與擴充套件中選較新者） |
| 模型／effort／期限 | sonnet／low／1800 秒總期限（含重試）、最多 3 次網路重試 |
| 伺服器 | `start.cmd`，`CELLFORGE_ENGINEERING_AGENT_MODE=claude`，Astra 為 local |
| OS／Python | Windows 11 Home 10.0.26200／3.12.10 |
| 網路 | 可連線（D-028 當時的 ConnectionRefused 在本輪未出現） |

## 3. 輸入（D-001 真實資料，共 13 個）

| 種類 | 檔案 | SHA-256 |
|---|---|---|
| inspection_spec | QII-RSBU-P5-V110系列_R00-002.pdf | `9d77d2b8e01d6431ea43989048fec58061ea302627506add269d8f2722a5a406` |
| checklist | RMK12608372(LFF126071920).xls | `ffb9049e64f5e5f1eb3cbbab2e485a6f6ee42af4da1bce370f0db16597dc53c0` |
| product_photo | PXL_20260903_030641421.jpg | `e5a2dca96ec8ce699b251ad5becde4b5a8e2daa058a8aeb81e7907684bf8ab55` |
| product_photo | PXL_20260912_073020583.jpg | `ecbaa9122fbd3d1b82666a8a95834c12b0663761408612faa5cdf40b5281eee1` |
| product_photo | PXL_20260912_073030305.jpg | `4d417998595d75e64da5ea9bde4f5d7b19ed60bdb1c691d8865e180249021071` |
| product_photo | PXL_20260912_073050576.jpg | `e28c4d9091aedac8ba5e6c3162d10cc5c0ffcf5eee6e6c5fcb92b8fdb4b3d222` |
| product_photo | PXL_20260912_073109461.jpg | `0572adaff2f5c59ecc0020d91efb8de821db8a98b4434b8df2752462c2c9611d` |
| product_photo | PXL_20260912_073138751.jpg | `33faac16b0bcbc68ba842d01becca4f040bb82ce82e876c7e5d9a0e96337d4a8` |
| product_photo | PXL_20260912_073158694.jpg | `239190ca5ee4a5a8b6949fc0f36630ad2991eae522de2fe2cd875f42ab54dd5e` |
| product_photo | PXL_20260912_073207860.jpg | `a839356028baec40db92bde684d58080b2416af01dc1ea17d55d6c6ac9e1d607` |
| product_photo | PXL_20260912_073208084.jpg | `b5ce04e0ce37c05f9379114bfa65e16140044e872c2c42fcf6e8b08c3bf1a557` |
| product_photo | PXL_20260912_073210434.jpg | `67df671779d221e5d4b3c7e2136e9231cd35b3348de63d8c6568addd6a25a9ad` |
| product_photo | PXL_20260912_073214307.jpg | `1f3571dac8c320a9476ac4d5e2953c92fa32d435031d18ad58dafcb3179ded38` |

intake 產生的 10 個問題全部依平台流程「略過」，採用 `default_if_skipped` 並建立 inferred 假設；沒有人工回答或代填工程事實。

## 4. 執行紀錄

案子目錄在 `.cellforge-runtime/projects/`（隔離案在 `.cellforge-runtime/isolated-projects/`），完整事件日誌在各案 `tasks/logs/<job>.jsonl`。

| 次 | 案（後綴） | job | 期間（09/28） | 結果 | 說明 |
|---|---|---|---|---|---|
| 1 | `_01` | intake `0a0655d64286` | 05:17–05:30 | 成功 | 16 張視覺判讀、Check List 73/73、12 個問題 |
| 1 | `_01` | first_build `0b2fb996724d` | 05:30–05:46 | 失敗 | 建出 v1、v2 後把修正交給背景子代理並結束回合，無最終 JSON（D-033） |
| 2 | `_02` | intake `466b6ece1c7a` | 05:58–06:13 | 成功 | 73/73、10 個問題；之後所有 first_build 都由此 intake 的提交出發 |
| 2 | `_02` | first_build `de52abd7d373` | 06:14–06:26 | 失敗 | v3 已驗證（red 65），代理因紅項未達 0 自評 failed（D-034） |
| 缺1 | `_02_缺模組重跑` | first_build `e9b3a7fc55d9` | 06:14–06:33 | 失敗 | 已自建 fixture_stand、v2 已驗證（red 102），同樣自評 failed（D-034） |
| 3 | `_03` | first_build `d6cd2423db16` | 07:13–07:43 | 失敗 | 1800 秒期限終止；單次 cell build 卡住 15 分鐘以上（D-035） |
| 4 | `_04_缺模組` | first_build `37e4bd01ef8f` | 07:16–07:46 | 失敗 | 同上 |
| 5 | `_05` | first_build `221d03581473` | 09:31–09:46 | **成功** | 發布 v1～v17，v17 驗證通過、red 137 |
| 6 | `_06_缺模組` | first_build `a4e5df03ccfd` | 09:31–09:53 | **成功** | 發布 v1～v19，v19 驗證通過、red 10；`parts/fixture_stand.py` |

第 3 次起的重跑以 `git clone` 複製 run 2 案子「intake 完成且問題已略過」的提交（`aff0cf2242`），intake 狀態、指紋與模式皆由平台驗證通過後才允許 first_build；未修改任何工程資料。缺模組的三次重跑在隔離平台副本（`git worktree` 位於 `.cellforge-runtime/isolated-platform`，只刪除 `library/fixture_stand.py` 與其 manifest 條目）上以第二個伺服器（port 8766、獨立案子根目錄）執行，`PYTHONPATH` 指向副本，已確認 `cellforge`、`library` 與 `source_root()` 皆解析到副本。

## 5. WP-A/C 規格 v1.2 第 9 節逐項

| # | 項目 | 實測 | 判定 |
|---|---|---|---|
| 1 | ≥17 個 production 模組 | 17 個模組，16 production、`box` 為 draft | 未達；依 D-026 延後，不以佔位盒湊數 |
| 2 | 既有模組通過 `cell part check` | 17/17 通過，0 fail、0 warn（`box` 以佔位規則放寬） | 通過 |
| 3 | 新增模組通過 check | 同上 | 通過 |
| 4 | 代理自建案內模組並通過 check | 正式 run 5 庫已齊全、未自建；隔離副本移除 `fixture_stand` 後 run 6 自建 `parts/fixture_stand.py`，0 fail／0 warn，供 `vision_fixture`、`connector_fixture` 使用，版本 manifest 的凍結庫模組不含 `fixture_stand` | 通過 |
| 5 | ≥15 個模組；S2／S3／S4 有相機與光源；capture 指向相機 frame | run 5：15 個模組；S2 相機站＋條燈、S4 相機站＋條燈，**S3 只有環燈、沒有相機模組**（S3 拍照由 robot_1 執行）；S3、S4 部分與 S5 的 capture 步驟 actor 不是相機 | 未完全達成 |
| 6 | L1 成功、< 90 秒、STEP 名稱與數量保留 | v17 建置 34.9 秒；STEP 16 個頂層元件、218 個 leaf，名稱與數量全數相符 | 通過（D-035 修正前為 126～157 秒，且部分建置無限期卡住） |
| 7 | ISO 與站別截圖目視 | 7 張截圖（ISO、俯視、S1～S5）可辨識料架層板、帶腳輸送段、相機站立柱與條燈、治具台孔陣、六軸手臂與力覺工具、翻面機構；**S3 環燈懸空無支撐**，且建置沒有發出懸空警告 | 設備型式通過；懸空問題列為缺陷 |
| 8 | 模組分頁列出模組 | API：`/api/library/modules` 17 項、`/projects/{p}/modules` 列出本案使用的 8 種；前端互動（分組、搜尋、篩選、三視圖）本輪未重新操作 | 部分（API 層） |
| 9 | `safety_door` 繞鉸鏈轉動 | 以正式 GLB 依 viewer 語意轉到 55°／110°，門扇 882 個頂點到鉸鏈軸距離漂移最大 2.3e-13 mm，最大位移 1474.7 mm | 通過（幾何量測） |
| 10 | `extrusion_frame` 逐桿件碰撞體 | 碰撞 mesh 拆成 24 個獨立盒，最大一個占外框包絡 0.16%，總和 1.3% | 通過（幾何量測） |
| 11 | 佔位輪廓與計數 | 代理產物沒有佔位模組；「刻意換成 box」情境本輪未執行 | 未重新驗證 |
| 12 | 「請代理修正」流程 | 本輪未執行 | 未驗證 |
| 13 | 模組快取 | 同一模組 check 連續兩次皆為快取命中（0.06／0.08 秒） | 通過 |
| 14 | 品質閘門 | pytest 157 項、ruff、前端三項閘門全綠（`a70c75c`） | 通過 |

## 6. 截圖

run 5（v17）截圖登記為 v17 的衍生檔（`.cellforge/derived/v17.json`），影像位於案內 `.cellforge/derived/v17/snapshots/`；run 6 的 ISO 與俯視截圖以主平台補拍（隔離副本沒有 `web/dist`，這也是 run 6 代理回報「無法截圖」的原因，屬測試佈置限制）。

## 7. 本輪修正的平台缺陷

| 決策 | 問題 | 處置 |
|---|---|---|
| D-033 | 伺服器從 Claude Code 內啟動時，代理繼承父工作階段標記與 `CLAUDE_EFFORT=xhigh` | 啟動代理前濾除工作階段標記 |
| D-033 | 代理把工作交給背景子代理後結束回合（run 1） | `--disallowedTools` 禁用 Agent／Task／Workflow／Monitor 等；prompt 明訂同步完成 |
| D-034 | 代理把「仍有紅項」當成失敗（run 2、缺1） | 發布有效 L1 版本即回 ok，紅項照實列出；job 結果帶 `engineering_status` 與警告 |
| D-035 | 直線移動時長推導遇 IK 跳解發散（29→404→5594 秒） | 最多放大 4 倍、依加密倍數判定跳解並記錄具體原因 |
| D-035 | FCL 帶號距離在凸體面貼面時無限迴圈且持有 GIL（run 3、4） | 改以 collide 取 contact depth、分離時用 GJK 距離 |
| D-035 | L1 寬相逐對 Python 比對占八成時間；FK 重建常數旋轉 | 向量化寬相、FK 快取；同一來源 173.5→33.0 秒且檢查結果逐項相同 |

## 8. 已知限制與未解問題

- **mount 只驗證 id 存在**：S3 環燈宣告了 `mount` 卻懸空，建置沒有警告。這是開發書 P4 已列的缺口（「延伸 mount 檢查，驗證支撐幾何或連接介面確實存在」），本輪不修。
- **工程收斂**：run 5 仍有 115 項干涉、16 項 reachability、5 項關節速度與節拍 85.3／45 秒；代理 summary 已逐項說明可能原因（手臂基座與工具姿態、翻面路徑、治具高度）。這些需要後續 CR 或人工複核，不是本輪驗收範圍。
- **WP-A/C 第 5 項**：S3 缺相機模組、部分 capture 未指向相機；屬代理的產線設計品質，本輪未為了通過而修改 prompt 或資料。
- **第 8、11、12 項**的前端互動與「請代理修正」流程本輪未重新操作。
- 隔離平台副本仍以 git worktree 形式保留在 `.cellforge-runtime/isolated-platform`（含未提交的「移除 fixture_stand」修改），以便重現缺模組情境；不需要時可用 `git worktree remove --force .cellforge-runtime/isolated-platform` 移除。
