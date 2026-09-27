# 專案電路圖產生器

各子專案以 `docs/electrical/circuit-data.json` 保存自身的元件、軸別、I/O、功能介面及設計註記。共用程式只負責繪圖，不改動 3D 模型、PLC 或現場設備。

```powershell
python tools/circuit-drawings/render.py
python tools/circuit-drawings/render.py "shutter assembly"
python tools/circuit-drawings/verify.py --render
```

需要 Python `reportlab`。Windows 預設使用 `C:/Windows/Fonts/msjh.ttc`，PDF 內嵌中文字型。其他環境可用 `CIRCUIT_FONT` 指定相容的繁中文字型 TTF／TTC 路徑。

每個專案產出：

- `docs/circuit-diagrams.pdf`：A3 橫式完整圖冊。
- `docs/circuit-diagrams.md`：圖紙索引、設計註記、相對 3D 的新增項與來源。
- `docs/electrical/E01.svg` 等：可編輯向量圖。

`TEMP/circuit-review/layout-checks.json` 記錄產生時的文字範圍／表格高度檢查，不能取代圖面目視審核。重新分頁時，只移除內容標題相符且超出新頁數的本工具舊 SVG。

P02 依使用者提供的《台全-壓鑄件檢測設備_V1.00_20260714.pdf》重排：A3 橫式座標圖框、底部專案與簽核欄、細黑線元件、洋紅電源、藍色 DC、綠色線號／PE，以及青色尺寸線。參考檔只用於版式分析，不複製到專案輸出，也不沿用其品牌、簽名或設備電氣額定。

`cad_sheets.py` 負責盤面、逐點 I/O、荷重元及驅動回路；`render.py` 負責共用 PDF/SVG 繪圖、圖框、功能接線與清單。各專案 JSON 的 `panels` 保留從現有 `panelSchedule` 取得的尺寸與元件資料，後续 3D 改版時需同步更新。長型 PCB 背板另提供局部放大頁；盤面上 LD-X/Z、UL-X/Z 分別對應 LOADX/Z、UNLOADX/Z。

圖紙編碼：P1 起為配置，100/101 為電源，102 起為介面，105 為安全，199 為典型 I/O，200 起為 DI，300 起為 DO，350 為量測，400 起為驅動，450 起為軸清單，500 起為 I/O 清單，600 起為元件清單，699 為設計依據。PDF 檔名與 SVG 檔名維持原路徑，重建直接覆蓋上一版。

`verify.py` 使用 pypdf、ReportLab 與 XML 檢查頁數、A3 尺寸、元件／軸／I/O 完整性、文字重疊及頁尾範圍；每個專案的 `docs/electrical/verification.json` 記錄目前 PDF 雜湊與檢查結果。`--render` 另需 Pillow 及 Poppler，可用 `PDFTOPPM` 指定執行檔。全部頁面與聯絡表輸出至忽略版控的 `TEMP/circuit-review/P02`，仍需目視審核線路與符號。

P02 是工程規劃圖，不是施工放行圖。現有專案未確定現場電源、完整負載表、I/O 料號、安全停止方案及原廠腳位，因此圖中保留待選項；X 端子、W 線號及 DI/DO 序號是分配草案。新增元件不會自動出現在既有 3D 或成本表。
