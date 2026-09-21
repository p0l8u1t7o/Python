# 首次建置任務

讀取所有已回答與已略過的問題。每個略過問題都必須有一則啟用中的 assumption，且
其文字等於 `default_if_skipped`。依需要更新推估的工程檔案，但不得更動既有 id。

以穩定的具名 frame（`<module>.<frame>`、`<robot>.tool` 與
`workpiece.<cover>.<hinge|edge>`）描述運動。目標 offset 是 frame 的局部座標，Z 軸是
接近／向外法向。IK 動作用 `move_to`，直線運動用 `linear: true`，搬運用
`grip`／`release`，支撐面之間移載用 `transfer`，機器人帶動蓋板用含 `driven_by` 的
`actuate`。跨站相依使用 `requires`／`emits`；不得把可平行的 actor 強制串行，也不得
虛構等待時間以通過 takt。

組線前先執行 `cell part list`，逐一確認規劃中的機構都有適用模組。缺件時依以下順序：

1. 先查模組庫；找到適用模組就只調參數。
2. 可採購且型號固定的 Tier V 元件先用 `cell vendor add`；取不到原廠檔才用
   `cell vendor stub`，並填入型錄的關鍵尺寸。
3. 依案調整尺寸的 Tier P 元件若庫內沒有，執行
   `cell part new <id> --category <category> --project .`，再把骨架改成真實機構。
4. 絕不可用 `library/box.py` 代替本來應自建的真實機構。

每個自建模組完成後執行 `cell part check <id> --project . --json`，依繁體中文原因修正，
最多重試三輪。三輪後仍失敗時，才把該 instance 降級成 `library/box.py` 佔位，設為
`trust: inferred`，在 `analysis/assumptions.yaml` 記錄原模組、佔位包絡與未解原因，並在
最終 JSON 的 `summary` 明說；不得靜默放過。每個尺寸的來源都寫入
`ModuleDef.meta.basis`；沒有型錄、實測或工程圖支持的估值，也必須建立 assumption。

以 `cell part render <id> --project . --out <隔離工作目錄>/<id>.png` 產生的圖，只交給
D-003 的隔離 vision job 目視檢查；本主工作階段不得直接 Read PNG／JPG。

執行 `cell validate --project . --json`，再執行
`cell build --project . --level L1 --json`。把每個紅／黃項目視為幾何、IK、限位、
payload／stroke／speed 或 takt 的量測證據；不得寫死檢查值或加入專案特例。於有意義的
運動／檢查時間產生 ISO、俯視與站別近景，並由隔離 vision job 驗證尺寸與機構外觀。
不得直接編輯 `build/`。

依要求回傳版本與檢查摘要的最終 JSON。`summary` 必須原樣列出所有仍使用
`meta.placeholder: true` 的 module instance；若沒有也要明說「沒有佔位模組」。
