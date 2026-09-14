# CellForge 開發決策

## D-001：以 `temp/` 的實際資料作為驗收輸入（2026-09-14）

開發書描述的預期資料與實際收到的內容不同。`temp/` 目前包含 1 份 35 頁檢驗規範 PDF、1 份舊版 XLS Check List，以及 11 張產品照片，共 13 個檔案。Step 2 以這批真實資料驗收；Step 0 仍以 `examples/getac_qc/handwritten/` 的五站 YAML 作為可重現基準。

## D-002：STEP 裝配改由 OCP XCAF 直接寫出（2026-09-14）

CadQuery `cq.Assembly.save(..., mode="default")` 的 STEP 無法穩定保留所需的裝配樹、instance label 與零件名稱，因此建置器改用 OCP XCAF 建立文件、component instance 與名稱，再寫出 STEP。

Step 0 的 OCP 回讀結果為：1 個 free shape、7 個頂層 component、46 個總 component、8 個 assembly node、39 個 leaf，且 YAML 中的 part／instance 名稱可在回讀結果找到。這項讀回驗證保留為建置後的必要檢查，避免問題延後到 SolidWorks 交付階段才發現。

## D-003：代理的影像理解採隔離子程序與內容快取（2026-09-14）

Claude CLI 在長上下文工作階段直接讀取多張高解析照片或 PDF 頁面時，可能長時間無輸出。Intake 因此先將照片修正 EXIF 方位並縮至最長邊 1024 px；每張產品照片及低文字量 PDF 圖頁各自交給一個有 60 秒硬逾時的唯讀 Claude 子程序產生證據摘要，再把摘要合併為 `analysis/extracted/vision.md` 供主工程代理閱讀。

摘要以來源檔 SHA-256 快取到 `analysis/extracted/vision.json`，重跑 intake 時不會重複分析未變更的影像。主工程代理另設 900 秒硬逾時，取消 job 時會在有限時間內終止子程序。

## D-004：正式代理與離線驗收模式分離（2026-09-14）

正式設定預設使用偵測到的最新版 Claude Code CLI、`sonnet` 模型、`low` effort 與真實 prompt／skills 流程。啟動 runner 前先執行 `--version` 與 `--help` 驗證介面；若 PATH 與編輯器 extension 同時存在 CLI，選擇語意版本較新的可執行檔。真實驗收發現新版 Sonnet 的預設 effort 可能在完成資料讀取後思考超過 900 秒而沒有新事件，因此 runner 在 CLI 支援時明確傳入可設定的 `--effort`；工程 job 的硬期限為 1800 秒，仍保證可取消且不會無限等待。

`local` runner 只供單元測試及無外部代理時的明確離線驗收，會產生可重現的問題、假設、checklist mapping 與 L0 build，但不取代正式 Claude intake 驗收。

## D-005：Windows 啟停必須有界且可重入（2026-09-14）

`start.cmd`／`stop.cmd` 只作為 PowerShell 包裝；實際腳本在 `scripts/`。啟動用隱藏背景程序執行 Uvicorn，以健康檢查與 15 秒預設硬期限決定成功或失敗，不等待伺服器程序結束。停止只會處理命令列與啟動時間都符合本 workspace metadata 的 PID，先正常終止、逾時後強制終止，預設上限 10 秒。重複啟動或停止皆應立即安全返回。

## D-006：Snapshot camera 必須由 URL 參數驅動（2026-09-14）

驗收時發現 `cell snapshot --cam top` 雖產生名為 top 的 PNG，檢視器卻忽略 `cam` query，因此內容仍是 ISO。Viewer 現在讀取 `cam=iso|top`，共用同一套 camera preset 給 URL 初始值與畫面按鈕。Snapshot helper 若輸出已位於最新 `.cellforge/vN`，會跳過 copy-to-self，避免 Windows 檔案鎖定錯誤。

## D-007：Windows L1 碰撞檢查採 20 ms swept AABB（2026-09-14）

`python-fcl` 在 Windows Python 3.12 的部署可用性不足，因此 L1 先使用可重現的 swept AABB 包絡、每 20 ms 取樣。`checks.json` 明確記錄 `native_fcl: false`、數值、限制與來源，保留日後換成 FCL 的契約。Getac 基準版實測法蘭間隙 −3.2 mm；CR-001 退 20 mm 後為 +16.8 mm，干涉項由紅轉綠。

## D-008：簡報範本與工具備案（2026-09-14）

開發書指定的 `zq-work-deck` 未出現在 workspace，Artifact Tool runtime 亦未由本工作階段提供。因此驗收 deck 採 CellForge Midnight 版式，以 Windows PowerPoint COM 產生原生可編輯文字與圖形，並逐張輸出 1920×1080 PNG 檢查。這項偏差寫入 export manifest；若日後提供範本與 runtime，應改回範本／Artifact Tool 流程。
