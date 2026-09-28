# P0 基準盤點（DEV-001）

日期：2026-09-27
依據：`docs/CellForge_平台擴充開發書_v2.0.md` 第 3 節與第 10 節 DEV-001。
本紀錄是實際執行的結果，不是開發書內容的轉述；「存在實作」與「本次已驗證」分開寫。

## 1. 版本與工作樹

| 項目 | 實測 |
|---|---|
| 分支 | `master`（本機唯一分支） |
| HEAD | `86cf152` 修正模擬引擎內插比例超界，並記錄真實代理驗收結果 |
| 與開發書基準提交 | 一致（開發書指定 `86cf152`） |
| 既有未提交修改 | 只有未追蹤的 `docs/CellForge_平台擴充開發書_v2.0.md`；經使用者同意與本紀錄一起提交 |

## 2. 工具環境

| 工具 | 版本 |
|---|---|
| OS | Windows 11 Home 10.0.26200 |
| Python（`.venv`） | 3.12.10 |
| cadquery／cadquery-ocp | 2.6.1／7.8.1.1.post1 |
| numpy／scipy | 2.5.3／1.18.1 |
| python-fcl／trimesh／pygltflib | 0.7.0.11／4.12.2／1.16.5 |
| pydantic／fastapi | 2.13.5／0.141.1 |
| PyMuPDF／imageio-ffmpeg／playwright | 1.28.2／0.6.0／1.62.0 |
| pytest／ruff | 9.1.1／0.16.7 |
| Node.js／npm | v24.21.0／11.19.0 |
| git | 2.55.0.windows.5 |
| Claude Code CLI（PATH） | 2.1.266，`C:\Users\grown\.local\bin\claude.exe` |
| Codex CLI | 存在，`%APPDATA%\npm\codex.ps1` |
| ffprobe | PATH 上不存在（P5 影片驗收需另外提供或改用 imageio-ffmpeg 內附 ffmpeg） |

## 3. 品質閘門（基準）

| 命令 | 結果 |
|---|---|
| `.venv\Scripts\python -m pytest` | 117 項通過，exit 0，約 359 秒 |
| `ruff check .` | All checks passed |
| `ruff format --check .` | 128 files already formatted |
| `npm run lint` | exit 0 |
| `npx tsc --noEmit` | exit 0 |
| `npm run build` | exit 0（Vite 對主 bundle 大於 500 kB 發出分塊建議，非錯誤） |

## 4. 開發書第 3 節逐項核對

| 項目 | 程式實況（`86cf152`） | 判定 |
|---|---|---|
| 工程資料 | `cellforge/schema/models.py` 有 project／workpiece／cell／process／checks／timeline 等模型；無 electrical、routing、costing、vision、版本 manifest 模型 | 與開發書相符 |
| 幾何與運動 | CadQuery、OCP XCAF STEP、GLB、FK／IK、FCL、timeline 均有實作與測試 | 與開發書相符 |
| 模組庫 | `library/manifest.yaml` 17 項；16 項 production，`box` 為 draft（D-026） | 與開發書相符 |
| 廠商模型 | `build/modules.py` 遇 `vendor:` 一律載入 `library/robot_stub.py` | 與開發書相符 |
| 版本輸出 | 見第 5 節，混版問題確認存在 | 與開發書相符，且範圍比開發書描述更大 |
| 成本 | `exports.py::_bom` 只列模組、數量固定 1、無價格 | 與開發書相符 |
| 電控 | `library/control_cabinet.py` 為外廓模組 | 與開發書相符 |
| 影片 | `agents/astra.py::render_video` 以最多三張 `build/` 截圖輪播 | 與開發書相符 |
| 真實代理 | 見第 6 節 | 與開發書相符 |
| 任務系統 | `server/jobs.py` 為記憶體 job 表，狀態只有 queued／running／done／failed／cancelled，重啟即遺失 | 與開發書相符 |

## 5. 版本一致性缺陷（DEV-002～DEV-004 的重現目標）

以下皆由閱讀程式確認，DEV-002 會以測試重現：

1. `exports.py` 只有 `step` 讀版本目錄；`dxf`、`bom` 讀工作區 `cell.yaml`／`vendor/manifest.yaml`，`report`、`deck`、`html` 讀工作區 `project.yaml`、`analysis/assumptions.yaml`、`analysis/checklist_map.md`、`process.yaml`、`workpiece.yaml`，匯出檔名的 slug 也取自工作區。
2. `video` 匯出直接複製 `presentation/cell_review_1080p.mp4`，也就是最近一次 Astra 產生的影片，與指定版本無關。
3. `_review_snapshots` 在版本目錄之外也搜尋 `build/`，deck 在沒有截圖時退回 `build/snapshot_station_s3.png`。
4. `snapshot.py::_copy_to_latest_version` 與人工驗收流程會把截圖寫進最新的 `.cellforge/vN`，改動已封存快照（`軍規筆電_QC_線_WPAC_驗收_20260921_01/.cellforge/v1/` 內有 `step11_acceptance_*.png`）。
5. `versioning.snapshot_build` 在建置完成後才從工作區複製來源，建置期間若 YAML 被改，快照來源與產物不一致；只保存 `SOURCE_FILES` 七個檔，缺 `animation/`、`parts/`、`analysis/questions.yaml`、`inputs/` 證據、實際使用的庫模組與執行環境。實際案子 `v1/source/` 只有六個檔（無 `checklist_map.md`）。
6. `build/pipeline.py` 以「目前最大版本號＋1」預先寫入 `checks.json` 的版本號，建置產物直接寫進共用的 `build/`；兩個建置並行時會互相覆蓋產物，版本號也可能與實際發布號不符。
7. `POST /api/projects/{p}/export` 的請求模型沒有 `version` 欄位，前端匯出按鈕也不傳目前選取的版本，永遠匯出最新版。

## 6. 真實代理驗收現況

`.cellforge-runtime/projects/` 的兩個 WP-A／WP-C 驗收案（`…_20260921_01`、`…_20260921_02`）共用同一批 job 紀錄：

| job | 種類 | 結果 |
|---|---|---|
| `16daf55d1586`、`81d8cb62ccf6` | intake | 失敗：Claude 視覺判讀超時（page-005.png） |
| `18afb8ff407c` | first_build | 失敗：Claude 工程代理退出碼 1（D-028 記錄的 ConnectionRefused） |
| `85c13511b6ea` | intake | 失敗：`git add` exit 128 |
| `cc42cfcd4530`（僅 `_02`） | first_build | 失敗：代理回報 `cell build` 觸發 SciPy 內插超界，該缺陷已由 `86cf152` 修正 |

兩案都有 `.cellforge/v1`，但建立時間（07:00:27、07:29:51）不落在任何成功的 job 內，不能當作正式代理驗收證據。結論：目前沒有「修正內插後、以正式代理完成 intake → first_build」的成功紀錄，DEV-006 仍未完成。

## 7. 另外發現的既有缺陷

**案內 `parts/` 模組無法建置。** `build/modules.py::load_part` 以 `importlib.import_module("parts.x")` 載入案內模組，但 `cell build` 子程序的 `sys.path` 不含案子目錄。以 getac 範例複製 `fixture_stand.py` 到 `parts/local_stand.py` 並在 `cell.yaml` 引用後，不論從平台根目錄執行 `python -m cellforge.cli build`、或在案子目錄執行 `cell build --project .`，都得到：

```
{"status": "failed", "message": "模組 vision_fixture 驗證失敗：No module named 'parts'"}
```

這會直接擋住 WP-A 驗收第 4 項（代理自建模組並建置）。DEV-003 從凍結來源建置時，改為以檔案路徑載入案內模組，並加回歸測試。

## 8. 本輪範圍

依開發書第 11 節，本輪只做 DEV-001～DEV-004。DEV-005（intake／first_build 前置狀態）與 DEV-006（真實 Getac 驗收）列為下一輪。
