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

## D-015：交接期間的工件支撐窗口（2026-09-14）

工件從模組 A 交接到模組 B 時，A 的支撐窗口延續到取件步驟結束，B 的窗口則自送達步驟開始；窗口由 timeline 的 `steps`、`attached_to` 與 process 目標 frame 所屬模組推導。模擬器的 `grip` 只切換 attachment、實際抬離在緊接的持件運動，因此該第一段運動也納入 A 的離場窗口。工件本體與蓋板在窗口內允許至多 1 mm 的接觸數值誤差，更深的穿透仍回報紅色，避免把實際掉入治具的問題掩蓋掉。

## D-016：線上與單檔 Viewer 共用關節取樣核心（2026-09-14）

React viewer 與離線 HTML 都呼叫 `web/src/viewer-core.ts`：先保存 GLB joint 節點的 rest TRS，再套用 timeline 的軸運動與工件 quaternion pose。離線版本另由 esbuild 產生單一 IIFE，匯出時連同 base64 GLB、timeline、checks 內嵌，因此 `file://` 不需網路、模組載入或後端服務，也避免兩套關節語意逐漸分歧。

## D-017：交付報告的檢查截圖選擇（2026-09-14）

報告與簡報若已有檢查時刻截圖，分別選最嚴重的 red、yellow 項目之最近時間 PNG；若沒有帶時間的截圖才沿用舊的總覽／S3 圖。匯出不自行啟動瀏覽器補拍，以免無 Playwright 的交付主機因產 DOCX/PPTX 而失敗。

## D-018：mount 是支撐宣告，不改寫世界姿態（2026-09-15）

`ModuleInstance.pose` 繼續作為唯一的世界姿態來源；`mount: <module_id>` 或 `<module_id>.<frame>` 表示模組由已存在的模組／frame 承載，供懸空檢查判斷，不建立第二套相對變換。未宣告有效 mount 的模組若最低幾何點高於地板 5 mm，或任何模組低於地板 5 mm，建置均產生中文警告。這避免既有 cell.yaml 的 pose 語意被靜默改變，也讓刻意架高的感測器有可稽核的支撐關係。

## D-019：工程配色與信任度提示分離（2026-09-15）

GLB 保留每個 CadQuery 子零件的 `cq.Color`，未指定色彩才使用中性鋼色。`trust: inferred` 不再覆蓋材質底色；線上 viewer 與離線 viewer 先按位置焊接顯示網格，再由 `EdgesGeometry` 畫細琥珀輪廓，檢查物件才使用紅色 emissive 高亮。如此能同時辨識設備／零件配色與資料信任狀態。實拍確認低強度的全表面琥珀 emissive 仍會讓白色手臂偏成紅褐色，而未焊接三角網格的邊線會覆蓋表面，因此兩者均不採用。

## D-020：Viewer 以 GLB extras 辨識碰撞節點（2026-09-15）

GLB 中每個 link 都可有名為 `collision` 的子節點，但 Three.js 載入時會為重名物件自動加上 `_1`、`_2` 後綴。Viewer 因此不再以顯示名稱切換碰撞體，而以 exporter 寫入的 `extras.hidden: true`（載入後為 `userData.hidden`）辨識。這也避免紅色碰撞材質在預設模式覆蓋工程配色。

## D-021：保留模組碰撞膨脹比與三角形數門檻（2026-09-20）

依規格 6.6 與 11，先以預設參數實測既有九個 `library/` 模組。碰撞體沿用 GLB 建置管線的 `_collision_mesh`，逐一套用在具名 visual 子零件後加總體積；visual 網格沿用 `_shape_mesh` 的相同線性與角度容差。結果如下：

| 模組 | 碰撞膨脹比 | 三角形數 |
|---|---:|---:|
| `box` | 1.000000 | 12 |
| `camera_light` | 1.341554 | 44 |
| `conveyor` | 1.000000 | 72 |
| `fixture_stand` | 1.000000 | 36 |
| `flip_fixture` | 1.174409 | 272 |
| `force_eoat` | 1.278758 | 272 |
| `lift_rack` | 3.620002 | 120 |
| `robot_stub` | 0.998705 | 1,748 |
| `safety_fence` | 1.000000 | 36 |

決定保留膨脹比 `> 3.0` 警告、`> 6.0` 失敗，以及三角形數 `> 50,000` 警告、`> 150,000` 失敗。八個箱體層級模組的膨脹比接近 1；`lift_rack` 的多層板被同一具名 compound 的 box 碰撞體包住層間空隙，實測 3.62，正確觸發警告並指出步驟 5 應拆成逐桿件／逐層碰撞體。九個既有模組的三角形數都遠低於預算，不構成調高門檻的依據；保留規格值可讓後續細節升級仍有明確上限。

## D-022：單模組四視圖採共用網格的無頭軟體投影（2026-09-21）

`snapshot_project` 只接受完整案子的 `build/scene.glb` 與 `timeline.json`，現有 viewer 相機只提供 ISO、俯視與站別透視，無法直接產生單模組的前視、側視。為了只做 `cell part render` 而修改前端與已建置 bundle，會把步驟 8～9 的工作提前，且安裝環境若沒有 Playwright Chromium 就完全無法出圖。

因此單模組 render 直接重用 `cellforge.build.glb._assembly_meshes` 的同一份 tessellation 與工程配色，以 Pillow 做四個正投影面板與單張 PNG 合成；不依賴 GPU、瀏覽器、`cell.yaml` 或暫存案子。這項 render 僅供品質目視，不建立第二套 GLB 語意；`cell part preview` 仍原樣呼叫正式 `export_glb`，保留 joint hierarchy、rest TRS、碰撞節點 extras 與材質。

## D-023：以 frame 明示自由空間工作點，並以 assembly metadata 綁定可動 link（2026-09-21）

規格 7.1 要求 `extrusion_frame.inner_center` 位於框架內部中心，但 6.4 又以距最近實體表面超過 20 mm 發出警告；同一規格也明訂光學中心、抓取點等空間點在機構學上合法。刪除 `inner_center` 或把它移到桿件表面都會破壞 frame 的工程語意，也無法達成示範模組零警告的要求。

因此 `Frame` 新增相容的 `free_space: bool = false`。設為 true 時，只豁免 6.4 的表面距離代理警告；frame 仍必須位於整體包圍盒內，且 `link` 仍須存在。`extrusion_frame.inner_center` 與位於底面中心的 `mount` 明確標示為自由空間點，其餘 frame 繼續接受完整表面檢查。

另為落實 7.2 的零位世界座標規則，CadQuery 子零件以既有 assembly `metadata.link` 指定 `base` 或 `door`；GLB 分組與 FCL 幾何讀取此通用標記。門扇仍直接畫在關門時的世界位置，由 GLB 匯出器按 `swing` 的 rest transform 反算 joint-local，不在模組內預平移，避免轉動時整扇門繞錯軸飛離。

## D-024：manifest 結構欄位由 ModuleDef 驗證，未升級模組維持 draft（2026-09-21）

規格要求 `library/manifest.yaml` 保存 params、frames、axes 與 basis，但這些欄位同時存在於 Python `ModuleDef`，若由人工各自維護就會漂移。此外步驟 5a 只完成結構整理，既有九個模組尚未進行 5b 的幾何升級，不應先宣告為 production。

處置為以 `derive_module_fields()` 載入預設參數下的動態 `ModuleDef`，程式化取得 id、file、basis、params、frames、axes；`cell part list` 每次讀 manifest 都逐欄比對，任一漂移即以中文錯誤拒絕，測試也覆蓋所有 library Python 檔。只有已達零警告的兩個示範模組標為 production；既有九個模組（含 placeholder `box`）在 5b 完成前維持 draft。`robot_stub` 是廠商模型不可得時的型錄近似，因此列 Tier V，其餘自建模組列 Tier P。

## D-025：相機與光源拆為三個 library 型別（2026-09-21）

問題：規格 3.2 要求把同時包含相機與漫射光源的 `camera_light` 拆開，但共通約定又要求所有 id 不更名。若保留舊型別並另外新增光源，代理仍可能選到把安裝架與照明綁死的錯誤抽象；若把既有專案 instance id 一併改名，則會破壞 process 與 frame 引用。

處置：移除未被任何 tracked 範例引用的 library 型別 `camera_light`，改為 `camera_bracket`、`light_ring`、`light_bar` 三個各自可參數化且可獨立安裝的型別；`camera_bracket` 保留 `optical` 的功能語意，兩種光源統一提供 `mount` 與 `emit`。全庫搜尋確認沒有 cell.yaml、template 或 process 引用舊型別，測試與現況文件改指向新型別；規格原文及 D-021 的歷史量測表保留不改。

理由：共通約定的 id 穩定性保護的是已落入專案的 module instance、axis 與 frame 引用，不能阻止規格明訂且尚未被專案採用的 library 型別拆分。以三個單一職責型別取代舊整合頭，才能讓相機支架、同軸環燈與條燈依實際站別分別選型，且不需遷移任何既有專案資料。

## D-026：步驟 5c 完成後保留 box 為非 production 佔位模組（2026-09-21）

問題：步驟 5c 明訂新增四個 production 模組，完成後 library 共十七個模組；但規格 9.1 同時要求至少十七個 production 模組。既有 `box` 又依規格 3.2 明訂為 `meta.placeholder: true`，D-024 也要求未達正式工程幾何者維持 draft。若只為湊足數量而把 `box` 標為 production，會讓目錄狀態誤導代理與使用者；另增規格外第五個模組則超出本步驟範圍。

處置：四個新模組均列為 production，`box` 繼續列為 draft，因此目錄為十七個可用模組、十六個 production 模組。規格 9.1 的十七個 production 門檻延後到新增另一個具正式工程幾何的模組時達成，不以佔位盒冒充正式樣板。

理由：manifest 的 status 是品質承諾而非單純計數欄位；維持可追溯的真實狀態，比隱藏一個仍受佔位放寬規則處理的模組更符合工程用途，也遵守本步驟不得修改既有模組的限制。

## D-027：單一模組端點的參數選擇與 promote 類別來源（2026-09-21）

問題：第 8.5 節的模組詳情、check、render 與 preview 路徑只有模組型別 `{id}`，但同一案子可能以不同參數多次使用同一個案內 `parts/` 模組，路徑本身無法指定哪一組參數。另第 4.1 節的 `cell part promote <id>` 沒有 category 參數，而 manifest 又強制 category 必須是規格列舉值；現有 `ModuleDef` 也沒有必填 category 欄位。

處置：庫模組一律依規格使用預設參數；案內模組按 `cell.yaml` 的 machine／module 順序取第一組實際參數作詳情資產，同時在 API 的 `parameter_sets` 與 `usages` 完整回傳所有不同參數組與使用位置，讓後續前端能揭露歧義。promote 優先讀模組頂層 `CATEGORY`，其次讀 `meta.category` 擴充欄位；兩者皆無時採廣義的 `handling`，CLI 另提供可選的 `--category` 明確覆寫。promotion 會移動檔案、更新所有 `cell.yaml` 引用並填入 `from_project`，不留下會漂移的雙份來源。

理由：這保留規格既定的簡潔 URL 與 CLI，同時不隱藏多實例參數；類別來源有明確優先序，既有案內模組不必先改 schema 才能收進庫。未來若 UI 需要逐參數組預覽，可在不破壞目前端點的前提下增加 query parameter。

## D-028：真實代理驗收遇到外部連線失敗時保留失敗結果（2026-09-21）

問題：以 D-001 的十三個真實輸入、`claude`／`sonnet`／`low` 正式設定建立全新驗收案後，兩次 intake 都在第一張視覺頁面達到既定六十秒上限並回報「Claude 視覺判讀超時」；後續 first_build 雖由 API 排入並啟動 Claude Code 2.1.278，仍在一百九十一秒後因 `ConnectionRefused` 退出。這個環境沒有可用的代理服務連線，因此無法產生可供第 9 節驗收的真實線體。

處置：不調高硬逾時、不切換 local runner、不人工改寫 `cell.yaml`、`process.yaml` 或 `parts/`，也不以手寫範例冒充代理輸出。保留兩次 intake 與 first_build 的完整 job log，繼續量測不依賴代理產物的模組庫、前端、快取與品質閘門；依賴新線體或代理修正的項目一律明列未通過。

理由：第 9 節是對真實代理端到端能力的驗收，外部服務不可達本身就是驗收結果。以離線代理或人工產物補齊會重演規格明確禁止的假驗收，且會掩蓋 first_build 路由在 intake 失敗後仍可啟動的實際行為。
