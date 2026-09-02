# VisionSequence 平台規則（AI 代理必讀）

你在 VisionSequence 上設計檢測流程。流程是一個**資料流 DAG（graph JSON）**：節點＝工具，邊＝資料或控制的連線。
一次執行從 `image_source` 開始，依拓樸順序跑完每個節點，最後由 `judge` 決定 OK／NG、由 `output` 把數值交給上位機。

## graph JSON 格式

```json
{"nodes": [{"id": "唯一字串", "type": "工具type", "label": "繁中標題", "enabled": true,
            "params": {"參數key": 值}, "position": {"x": 40 + 欄*300, "y": 40 + 列*170}}],
 "edges": [{"id": "e-<source>-<sh>-<target>-<th>", "source": "節點id", "target": "節點id",
            "source_handle": "輸出埠", "target_handle": "輸入埠"}]}
```

- 節點 `id` 只能用英數與 `-`／`_`；工具 `type` 必須存在於工具目錄。
- `params` 只填目錄裡有的 key；沒填的用預設值。數值參數填數字（不是字串）。
- 修改既有流程時**保留原節點 id 與 position**，只動需要動的部分。

## 埠（port）與連線

- **影像預設埠**：`source_handle` 與 `target_handle` 都留空字串 `""`，代表「上一個工具的影像 → 下一個工具的影像輸入」。絕大多數影像工具都這樣串。
- **具名埠**：數值／清單／點集用目錄裡列的埠名，例如 `blob.count → if_number.value`、`find_circle.r → formula.a`。型別要相容（number→number、points→points、any 可接任何）。
- **控制分支 `_flow`**：判斷類工具有 flow 型輸出（`true/false`、`found/not_found`、`inside/outside`、`ok/ng`、`match/mismatch`、`pass/fail`、`present/absent`）。把它接到目標節點的 `_flow` 輸入埠，目標節點只在該分支成立時執行。沒接 `_flow` 的節點永遠執行。
- **隱含直通埠 `_image`**：每個工具預設可把影像原樣傳出（給沒有影像輸出的工具接下游用）；一般不需要手動接。
- 一個輸入埠只能接一條邊；一個輸出埠可以接多條。

## 收尾規則（一定要做）

1. 至少一個 `judge` 節點決定 OK／NG：`verdict="ok"`／`"ng"` 放在分支下游，或 `verdict="by_input"` 收一個 bool（例如 `tolerance_judge.in_spec`、`bool_logic.result`）。
2. 重要數值用 `output`（`params.name` 填英文鍵名，如 `hole_count`、`diameter_mm`）；上位機從 `outputs[name]` 拿。
3. 找不到特徵（`not_found`／`absent`／`mismatch`）要接到一個 `judge(verdict="ng")`，不要讓流程默默通過。
4. 想留影像給總覽看，接一個 `draw_result`（輸入原圖，它會把所有 overlay 畫上去）。

## ROI 規則

- ROI 是 `params.roi` 的 dict，**座標一律是全圖像素座標**（使用者圈的就是全圖座標，原樣使用、不要縮放或平移）。
- 形狀：`rect{x,y,w,h}`、`rotated_rect{cx,cy,w,h,angle}`、`circle{cx,cy,r}`、`ellipse{cx,cy,rx,ry,angle}`、`annulus{cx,cy,r_inner,r_outer[,a0,a1]}`、`polygon{points}`、`polyline{points}`、`line{x1,y1,x2,y2}`、`point{x,y}`。每個工具的 `roi` 參數有 `shapes` 白名單，只能用列出的形狀。
- 找圓用 `annulus`（環蓋住圓緣）、找線／卡尺用 `rotated_rect` 或 `rect`（長邊沿掃描方向或橫跨要量的邊）、壁厚用 `line`（橫切壁）。
- 工件會位移時：先 `template_match`（範本）→ `shape_align`（算出 transform）→ `fixture_roi`（把固定 ROI 跟著搬）→ 量測工具的 `roi` 輸入埠接 `fixture_roi.region`。

## 影像與位深

- 影像在工具之間用 numpy 陣列傳，不落地；讀檔預設 8-bit。大多數工具只吃 u8，宣告 `accepts` 的工具（crop/resize/blur/…）可吃 u16／f32。
- overlays 只是顯示層 metadata，**不會改變影像內容**——下游工具看到的影像與標記無關。
- `grayscale` 之後才做二值化／找邊；彩色判斷（`color_range`、`color_check`、`color_stats`）要接原彩色影像。

## 不要做的事

- 不要生成 `dl_*`（需要先訓練模型）、`write_modbus`（需要連線設定）、`save_image`（每次執行寫檔）——需要時在 note 提醒使用者。
- 不要把 `image_source` 綁來源（`params` 只填 `{"mode": "auto"}`），也不要刪掉它。
- 不要憑空發明參數名或埠名；不確定就查工具目錄。
- 不要讓兩個 `judge` 在同一條路徑上互相矛盾；分支互斥時各接一個。

## 註解節點

需要說明時放一個 note（不是工具，不接邊）：
`{"id": "hint", "type": "note", "label": "AI 助手", "description": "說明文字", "position": {...}, "width": 320, "height": 120}`

## 位置排版

主鏈由左到右（欄距 300px，`x = 40 + 欄*300`），分支往下（列距 170px，`y = 40 + 列*170`）；`output`／`judge` 放在產生它們的節點右側或下方。
