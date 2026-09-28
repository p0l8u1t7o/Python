# CellForge — 代理工作規範

自動化設備可行性評估平台。工程真相放在 YAML、CadQuery 模組與廠商 URDF／STEP；每次建置產出具名 STEP 組件、階層化 GLB、取樣 timeline 與 L1 證據。

## 目前任務

**`docs/CellForge_平台擴充開發書_v2.0.md`** — 平台擴充 P0～P7，依其任務清單 DEV-001～DEV-015 依序執行（已完成項目在清單中打勾）。目前進行 **DEV-010**，暫停時的進度與待辦見 **`docs/DEV010_PROGRESS.md`**，恢復工作前先讀。該文件與本檔衝突時以該文件為準。

既有 WP-A／WP-C（`docs/CellForge_WP-A-C_規格_v1.2.md`）已於 DEV-006 驗收收尾，仍是背景規範。

其他必讀背景：`docs/DECISIONS.md`（既有決策 D-001 起；D-011 的 Windows 載入順序、D-036 之後的平台擴充決策與目前任務直接相關）、`docs/ENGINE_REWORK_PLAN.md` 第 1 節（共通約定）。

## 共通約定

- 單位 mm、角度度；右手系、Z 向上。URDF 檔依規範一律視為公尺與弧度，載入時換算。
- 位姿 `rpy_deg` 語意：繞父 frame X→Y→Z 固定軸，`R = Rz·Ry·Rx`（見 `cellforge/build/transforms.py`）。
- **不得寫死任何驗收數值。** 所有 check 的數值必須由幾何／運動學算出；測試不得斷言特定魔術數字，只能斷言嚴重度與因果（改前紅、改後非紅、數值合理範圍）。這條是本專案最重要的規則——步驟 3～6 曾因違反它而整個重做，見 `docs/ENGINE_REWORK_PLAN.md` 第 0 節。
- 所有 id 不更名。
- 錯誤訊息一律繁體中文（會直接顯示給使用者與代理）。
- 不可刪除 schema 既有欄位；可加欄位。改了 pydantic 模型要重新輸出 `docs/schema/*.json`。
- 推估內容必須標 `trust: inferred`，並在 `analysis/assumptions.yaml` 建立對應假設。不可自行把 inferred 升級為 confirmed。
- 無法確認的工程資訊列入 `analysis/questions.yaml`，不可猜測後當成事實。
- 不可直接編輯 `build/` 或 `.cellforge/vN`。

## 品質閘門

每個開發步驟結束時必須通過：

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check .
.\.venv\Scripts\python -m ruff format --check .
```

前端有改動時另外：

```powershell
cd web
npm run lint
npx tsc --noEmit
npm run build
```

通過後提交一次 git，commit 訊息用繁體中文說明做了什麼。

## Windows 環境注意事項

- **nlopt 替身**：`cellforge/__init__.py` 在 Windows 上把 `nlopt` 換成替身模組，避免 casadi 與 nlopt 同時載入導致直譯器結束時崩潰。`library/__init__.py` 先載入 cellforge 以確保替身早於 `import cadquery` 生效。不要移除這個機制（D-011）。
- **PyMuPDF 載入順序**：先建立 OCP XCAF 物件之後再 `import pymupdf` 會崩潰。後端在模組頂端就載入 `cellforge.intake`，pytest 由 `tests/conftest.py` 在收集前載入 PyMuPDF。不要更動這個順序（D-011）。
- Python 用 `.venv\Scripts\python`，不要用系統 python。

## 決策紀錄

實作時若發現規格窒礙難行或內部矛盾，**在 `docs/DECISIONS.md` 新增一則 D-0xx 記錄偏離原因後繼續**，不要停下來等待。格式參照既有條目：標題、日期、問題、處置、理由。

## 專案結構

```
cellforge/     Python 套件（schema、build、checks、kinematics、sim、agents、exports、cli）
server/        FastAPI（main、jobs、routes/api）
web/           Vite + React + TypeScript + Three.js
library/       跨案共用參數化模組
skills/        工程代理的 skills
templates/     cell init 的案子骨架
examples/      驗收用案例
docs/          規格與決策
```

執行中的案子在 `.cellforge-runtime/projects/`（不在版控內）。
