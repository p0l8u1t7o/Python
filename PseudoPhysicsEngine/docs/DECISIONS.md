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

## D-007：Windows L1 碰撞核心採 python-fcl（2026-09-14，修訂）

已確認 Python 3.12 可安裝並載入 `python-fcl 0.7`，因此原先「Windows 不可用」的判斷撤回，依賴正式列入 `pyproject.toml`。既有 L1 寫死間隙與 swept AABB 邏輯只為 WP1 相容而暫留，將在 WP3 以 FCL 帶號距離及實際幾何取樣完整取代；舊有 −3.2／16.8 mm 不再視為工程驗收值。

## D-008：簡報範本與工具備案（2026-09-14）

開發書指定的 `zq-work-deck` 未出現在 workspace，Artifact Tool runtime 亦未由本工作階段提供。因此驗收 deck 採 CellForge Midnight 版式，以 Windows PowerPoint COM 產生原生可編輯文字與圖形，並逐張輸出 1920×1080 PNG 檢查。這項偏差寫入 export manifest；若日後提供範本與 runtime，應改回範本／Artifact Tool 流程。

## D-009：WP1 關節 frame、URDF 單位與工件初始姿態（2026-09-14）

關節採 URDF 語意：`origin` 是 parent link 到零位 child link 的變換，`axis` 表示在 joint frame；CellForge 記憶體與 GLB extras 使用 mm／度，URDF 讀寫則固定換成公尺／弧度。GLB 的模組根節點代表 `base`（手臂為 `link0`），各 child link 幾何先乘其零位世界變換的反矩陣，再掛到保存 rest TRS 的關節節點；固定的 `tool` 節點代表 TCP，Z 軸沿 link6 的 +X。

WP1 尚未包含工件流程模擬，因此工件根節點與 STEP 頂層組件先放在世界原點；WP2 再由 timeline 驅動其世界姿態。動態模組 frame 以實際 params 生成並寫入模組 GLB extras；工件也納入 STEP 裝配，以確保交付幾何與 GLB 場景一致。

## D-010：單工件排程與初始放置 frame（2026-09-14）

WP2 以單一工件模擬 first-article cycle；同站順序、同 actor 與工件持有動作會自動序列化，站別第一步未寫 `requires` 時隱含等待前一站的 `<station>.done`，明寫 `requires` 則可讓不同站平行。穩態多工件節拍留待 WP3 以各站瓶頸估算，不在此複製工件實體。

規格未定義工件在 t=0 的資料欄位，因此新增相容的 `process.initial_workpiece_frame`；模擬器以該具名 frame 求世界位姿與支撐模組，不從步驟內容猜測，也不把範例座標寫死在引擎內。工件姿態、附著關係與所有 IK 失敗均烘焙到 timeline，後續檢查只取樣而不重解 IK。

## D-011：Windows 上 python.exe 結束時崩潰的兩個來源（2026-09-14，實測後修訂）

症狀：程序在所有工作完成後、直譯器結束清理時崩潰，跳出「python.exe - 應用程式錯誤／記憶體不能為 read」對話框，exit code 為 0xC0000005 或 0xC0000374。輸出檔案通常已寫完，但錯誤碼會讓 CLI 與 job 被誤判為失敗。以逐一載入的子程序實測，查到兩個互相獨立的來源：

1. **casadi 與 nlopt 同時載入**：cadquery 初始化時兩者都會載入。最小重現為 `import casadi; import nlopt`；與載入順序無關，換版本（casadi 3.6.7～3.8.0 × nlopt 2.9.1～2.11.0）、限制 OpenMP／OpenBLAS 執行緒、`importlib.util.LazyLoader` 皆無效。處置：`cellforge/__init__.py` 在 Windows 上把 `nlopt` 換成替身模組（nlopt 只給 cadquery 的草圖約束求解器使用，CellForge 用不到；真的被呼叫時丟出中文錯誤）。`library/__init__.py` 先載入 cellforge，確保替身比各模組的 `import cadquery` 更早生效。需要 nlopt 時設 `CELLFORGE_ALLOW_NLOPT=1`。
2. **先建立 OCP XCAF 物件、之後才載入 PyMuPDF**：建置後 `import pymupdf` 會崩潰，先載入 PyMuPDF 再建置則正常。`cell build`、`cell validate`、同程序 `build_project`、建置後載入 Playwright 皆正常。後端在模組頂端就載入 `cellforge.intake`（連帶載入 PyMuPDF），順序本來就安全；pytest 則由 `tests/conftest.py` 在收集測試前先載入 PyMuPDF。原先以 `atexit` 呼叫 `os._exit` 跳過清理、強制重排測試順序的作法已移除，避免掩蓋其他原生問題。

local API 模式以 `cell build --json` 子程序執行工程建置（WP2 引入），保留此作法的理由是隔離：建置中的原生崩潰只會讓該 job 失敗，不會拖垮整個後端。

開發機的 `.venv` 另放 `Lib/site-packages/zz_cellforge_crash_guard.pth`＋`cellforge_crash_guard.py`：每個 python 程序啟動時關閉 Windows 崩潰對話框（`SetErrorMode`）、以 faulthandler 把崩潰程序的命令列與堆疊追加到 `%TEMP%\cellforge-crash\YYYYMMDD.log`，並先載入 cellforge。這兩個檔案不在版控內，只用於開發與代理大量執行測試時避免彈窗；重建 venv 後如需同樣保護，須再複製一次。

## D-012：靜態物件的接近警告（2026-09-14）

WP3 本次驗收明列「兩個靜態箱體相距 5 mm 應為黃色」，與引擎計畫 5.1 的「靜態↔靜態不報黃」衝突。依較新的明確驗收要求，靜態配對仍只在 t=0 評估一次；穿透超過 1 mm 報紅，未穿透但距離小於 10 mm 報黃。這保留佈局淨空預警，又不增加後續時間樣本成本。

## D-013：同軸腕部的相鄰碰撞排除（2026-09-14）

stub 手臂的 j5 與 j6 關節原點重合，link4、link5、link6 是同一腕部關節殼；只按圖論的一條 edge 排除會把隔著零長度 link 的 link4↔link6 誤報為自碰撞。碰撞器因此把「經過零位移關節相連」視為機械上的相鄰 link；其他非相鄰 link 仍照常檢查。

## D-014：FCL 凸包穿透深度 fallback（2026-09-14）

Windows 的 python-fcl 0.7 對剛好接觸的 `fcl.Convex` 偶爾回傳負的 signed distance，卻沒有 collision contact；該數值可能沿箱體長邊而非分離方向，不能當穿透深度。檢查器仍先呼叫 `DistanceRequest(enable_signed_distance=True)`；負值時優先採 FCL contact depth，無 contact 時採世界 AABB 最小重疊深度。每筆使用替代值的 check 都在 `source` 明列 fallback 名稱。
