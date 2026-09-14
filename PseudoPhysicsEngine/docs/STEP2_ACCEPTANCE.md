# Step 2 驗收紀錄

日期：2026-09-14

## 驗收資料

使用 `temp/` 的真實資料建立 `Step2_Claude_Acceptance`：

- 1 份檢驗規範 PDF，共 35 頁。
- 1 份 XLS Check List，擷取 79 列原始內容。
- 11 張 4K 產品照片。
- 合計 13 個來源檔。

Intake 產生 16 份隔離式 Claude 視覺判讀快取（11 張照片、5 個低文字量 PDF 圖頁），主 session 僅讀取文字摘要。

## 真實 Claude intake

- Claude Code：2.1.270。
- 模型／effort：Sonnet／low。
- Job：`483b706065e6`，約 130 秒完成。
- 問題：12 題，符合 5～15 題要求，且每題都有 `default_if_skipped`。
- Check List：73/73，Coverage 100%，高於 80% 門檻。
- `cell validate --project . --json`：通過。
- Intake commit：`efec69e`（驗收案自己的 git repo）。

以 API 執行「全部跳過」後，12 題皆為 `skipped`，產生 12 筆 active assumptions；12 筆文字都精確等於來源問題的 `default_if_skipped`。

## 真實 Claude first build

- 第一次 job `0de31ca3608f` 已成功產生 v1 與三張 snapshot，但長 session 直接讀 PNG 後停止回報；API cancel 在 3 秒內收斂為 `cancelled`，未遺留 Claude 子程序。
- 因此 first-build prompt 改為不在主 session 讀圖，只檢查 PNG 存在、非零尺寸；影像理解一律使用隔離式 vision job。
- 重跑 job `b659a3804a86` 約 53 秒完成，回報版本 v2。
- Timeline 總長 114 秒，包含 S1～S5 五站。
- ISO、top、S3 snapshot 都是 1280×720；ISO 與 top 的 SHA-256 不同，並已目視確認 top 為真正俯視，而非 ISO 檔案誤命名。

## STEP／OCP 關鍵驗收

建置後另開新的 Python/OCP 程序，直接重讀 `.cellforge/v2/scene.step`，結果：

- free shape：1。
- 頂層 component：8，預期值也是 8。
- 總 component：48。
- assembly node：9。
- leaf part：40。
- `all_names_preserved`：true。
- `name_match`：true。
- `count_match`：true。
- `xcaf_fallback_used`：true。

回讀的頂層名稱依序為：`infeed_rack`、`conveyor_1`、`vision_fixture`、`robot_1`、`ac_connector_camera`、`robot_2`、`conveyor_2`、`outfeed_rack`，與 cell.yaml 預期名稱逐一一致。這證明 SolidWorks 交付路徑需要的裝配樹與零件名稱不是只看匯出成功，而是已由 OCP 真正重新開檔驗證。

## 可靠性修正

- Claude CLI 自動選擇可用的最高版本，並先驗證 `--version`／`--help`。
- CLI 支援時明確傳入 `--effort low`，避免新版 Sonnet 預設 thinking 讓工作在讀完資料後長時間無事件。
- 工程 job 有 1800 秒硬期限；影像 job 有 60 秒硬期限；取消會有限等待後 terminate／kill。
- Windows `cell` console wrapper 在輸出及檔案完成後以真實 Typer code 直接結束，避免 OCP DLL teardown 把成功命令誤報成 exit 1。
- Snapshot 已實作 `cam=iso|top`，且修正輸出本來就在最新版本目錄時的 self-copy 鎖檔錯誤。

## 最終測試

- `ruff check .`：通過。
- `pytest -q`：12 passed。
- 前端 `prettier --check`：通過。
- 前端 ESLint：通過，0 warnings。
- TypeScript `tsc --noEmit` 與 Vite production build：通過；只保留既有的 bundle 大於 500 kB 提示。
- 啟動運行中重複執行：0.52 秒、exit 0。
- 停止運行中服務：0.44 秒、exit 0。
- 已停止時重複停止：1.20 秒、exit 0。
