# CellForge 案子規範

- 單位 mm、右手座標系、Z 向上。
- id 一旦建立不可更名。
- 工程真相：`workpiece.yaml`、`cell.yaml`、`process.yaml`、`parts/`、`vendor/`、`animation/sequence.py`。
- 呈現層：`render/`、`viewer/theme/`、`animation/camera.yaml`、`animation/easing.yaml`。
- 工程代理可寫工程真相、`analysis/`、`tasks/`、`changes/`；呈現代理只可寫呈現層。
- `build/` 是工具產物，不得手動修改。
- 推估內容必須標示 `trust: inferred` 並寫入 `analysis/assumptions.yaml`，不得自行改成 `confirmed`。
- 無法確認的資訊必須列入 `analysis/questions.yaml`，不可當成事實。
- 修改後執行 `cell validate --project . && cell build --project . && cell snapshot --project . --t 0 --cam iso`。
- 截圖若有物件重疊、懸空或比例錯誤，須自行修正，最多三輪。
- 最後回報一行 JSON：`{"status":"ok|failed","version":N,"summary":"...","checks":{"red":0,"yellow":0}}`。
