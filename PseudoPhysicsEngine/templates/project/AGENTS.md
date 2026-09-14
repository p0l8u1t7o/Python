# CellForge 案子規範

- 單位 mm、右手座標系、Z 向上。
- id 一旦建立不可更名。
- 工程真相：`workpiece.yaml`、`cell.yaml`、`process.yaml`、`parts/`、`vendor/`、`animation/sequence.py`。
- 呈現層：`render/`、`viewer/theme/`、`animation/camera.yaml`、`animation/easing.yaml`。
- 工程代理可寫工程真相、`analysis/`、`tasks/`、`changes/`；呈現代理只可寫呈現層。
- `build/` 是工具產物，不得手動修改。
- 推估內容必須標示 `trust: inferred` 並寫入 `analysis/assumptions.yaml`，不得自行改成 `confirmed`。
- 無法確認的資訊必須列入 `analysis/questions.yaml`，不可當成事實。
- frame 命名固定為 `<module>.<frame>`、`<robot>.tool`、`workpiece.<cover>.<hinge|edge>`；offset 在 target frame 內表示，Z 為逼近／外法線方向。
- `move_to` 解 IK（`linear: true` 為直線路徑）；`move_joint` 為關節路徑；`grip/attach` 綁到 tool；`release/detach` 放到 frame；`transfer` 在支撐間搬運；`actuate` 驅動 ModuleDef axis；蓋板追蹤須填 `driven_by`。
- 同站步驟依序、跨站以 `requires`/`emits` 排程，同 actor 不可重疊。不可加假等待或改並行數來粉飾 takt。
- check 數值只能來自幾何、IK、關節／軸限制、質量、速度與 timeline；絕不可寫死驗收數字或為特定案例加例外。
- 修改後執行 `cell validate --project . && cell build --project . --level L1`，並在紅黃時刻及相關站別執行 `cell snapshot`。
- 截圖若有物件重疊、懸空或比例錯誤，須自行修正，最多三輪。
- 最後回報一行 JSON：`{"status":"ok|failed","version":N,"summary":"...","checks":{"red":0,"yellow":0}}`。
