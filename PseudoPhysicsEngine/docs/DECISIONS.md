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

## D-029：匯出器只經由 VersionContext 讀版本，舊快照以「涵蓋範圍」判斷缺件（2026-09-27）

問題：DEV-001 盤點確認 `exports.py` 除 STEP 外全部讀工作區，匯出 v1 時檔名、BOM、DXF、報告與離線頁都會混入 v2 或未建置的修改。改成讀快照時又遇到兩個判斷難題：既有 `.cellforge/vN` 沒有 manifest，無法分辨「建置當時就沒有這個檔」與「快照沒保存」；L0 版本本來就沒有 `checks.json`，原本的報告與離線頁會直接崩潰。

處置：新增 `cellforge.versioning.VersionContext` 作為匯出器、MCP 讀取工具與版本 diff 取得版本資料的唯一入口，版本名稱經 `normalize_version` 驗證，路徑不得超出該版本目錄。來源分必要與選用：必要來源缺少時丟出 `VersionIncompleteError`（「版本資料不完整：…不會改讀工作區或其他版本的資料」）；選用來源只有在該版本的凍結範圍涵蓋此路徑時，才可解讀為「建置當時不存在」。舊版快照的涵蓋範圍固定為 baseline 起 `SOURCE_FILES` 的七個檔（git 歷史確認自 `7e8a517` 起未變），範圍外的路徑一律視為未保存；新版快照的範圍由 manifest 的 `source_policy` 宣告（DEV-003）。舊版快照另帶警告，說明其來源是建置後複製且無雜湊。L0 版本缺 `checks.json` 時，報告、簡報與離線頁標示「未評估」，不填零也不視為通過。

理由：開發書 P0 要求所有匯出器只透過同一解析器讀指定版本，且舊快照資料不足時必須明示並停止需要缺失來源的輸出。以凍結範圍區分「確定不存在」與「未保存」，才能讓舊快照在資料足夠時繼續匯出，又不會把沒保存的資料靜默當成空白。影片匯出仍複製工作區最新影片，屬 DEV-004 的版本化衍生 artifact 範圍，於該步驟改正。

## D-030：建置先凍結來源到 staging，驗證後以單一 rename 發布版本（2026-09-27）

問題：原本的 `snapshot_build` 在建置寫完共用的 `build/` 之後，才從工作區複製七個來源檔，並以「目前最大版本號＋1」預先寫進 `checks.json`。建置期間工作區若被代理或 API 修改，快照來源與產物會不一致；兩個建置並行時會互相覆蓋 `build/`，版本號也可能與實際發布號不同；中途失敗則留下看似完整的 `build/`。此外案內 `parts/` 模組以 `import parts.x` 載入，`cell build` 子程序的 `sys.path` 沒有案子目錄，只要引用 `parts/` 就必定失敗（見 `docs/P0_BASELINE.md` 第 7 節）。

處置：新增 `cellforge/version_store.py`，`build_project` 改為：在發布鎖內保留版本號（每個保留持有一個作業系統檔案鎖，程序崩潰時鎖自動失效，下一次保留會回收號碼與殘留 staging）→ 依 `SOURCE_INCLUDE` 把案內來源凍結到 `.cellforge/_staging/vN-*/source`（複製時同步計算雜湊，記錄的雜湊必定等於副本）→ 只從凍結來源建置、只寫 staging → 回讀全部產物（非空、Timeline／Checks schema、`checks.json` 版本號、STEP 名稱與數量、GLB 頂層節點）並確認實際載入的庫模組在建置期間沒被改動 → 寫入 `manifest.json` → 以單一 `os.rename` 發布為 `.cellforge/vN`。任何一步失敗只會清掉 staging 並釋放保留，不產生版本。`build/` 改為最新版本的鏡像，舊版本不會覆蓋較新的鏡像，並以 `.cellforge_version.json` 標示所屬版本；鏡像或案子 git 提交失敗時版本已完整發布，只回報警告。

凍結範圍涵蓋 project／workpiece／cell／process、`inputs/`、`analysis/` 的文字檔與擷取文字、`animation/`、`parts/`、`vendor/`、`presentation` 的三份展示設定、`viewer/theme/` 與 `drawing_templates/`。輸入證據與 1 MiB 以上的檔案以 SHA-256 存到 `.cellforge/objects/`，版本內為硬連結（不支援時改複本），依使用者選擇的方案跨版本共用。實際使用的庫模組由 `cell.yaml` 的 `part`、巢狀工具 `part`、`vendor` 所需的 `robot_stub` 與原始碼中的 `library.*` 匯入遞移求得，複製到 `vN/library/`；每個模組另記實際傳入參數與套用 params_schema 預設值後的展開參數。建置時清除程序內已載入的 `library.*` 子模組，確保長駐程序（MCP）也從磁碟重新載入。案內 `parts/` 模組改以檔案路徑相對於凍結來源載入，模組名稱含內容雜湊；工具 `part` 亦走同一載入器。案子 git 的寫入以 `.git/cellforge.lock` 串行化。

理由：開發書 P0 要求「工作區輸入先凍結至 staging 再建置、完成後驗證輸出及雜湊並以原子方式發布、並行建置不得搶同一 vN、中斷不產生可被當成成功版本的半成品」。只從凍結副本建置，才能保證 manifest 記錄的來源就是產物的真正來源；以作業系統鎖作保留，崩潰後不必人工清理也不會留下號碼缺口。建置仍從工作中的共用庫載入模組而非凍結副本，因此以「建置前後雜湊一致」檢查取代，日後需要重建舊版本時，manifest 與 `vN/library/` 已足以還原當時的幾何來源。

## D-031：匯出逐項列缺件，截圖與影片改為登記在版本名下的衍生檔（2026-09-27）

問題：DEV-002 之後匯出器已只讀指定版本，但仍有三個缺口：影片匯出直接複製工作區 `presentation/cell_review_1080p.mp4`（最近一次 Astra 的產物，與版本無關）；`cell snapshot` 會把截圖寫進最新的 `.cellforge/vN`，改動已封存快照；匯出任一項缺資料就整包例外，舊匯出目錄內的同名檔（例如舊匯出器複製進來的最新版影片）仍可被 `GET /export/{filename}` 下載。另外 DEV-004 的 API 測試發現 `POST /api/projects/{p}/export` 是同步函式，FastAPI 把它放進 threadpool 執行，`JobRunner.submit` 取不到 event loop，前端匯出按鈕原本必定失敗。

處置：依使用者選擇，「全部匯出」時缺資料的項目不中止整包：該項列入 `missing`（附中文原因）、刪除匯出目錄內的同名舊檔，其餘照常輸出，交付包 `manifest.json` 與 API／CLI 回傳 `status: incomplete`；只有 `VersionError` 類（版本資料不完整、雜湊不符、衍生檔缺少）會被收斂成缺件，其他錯誤仍讓工作失敗。交付包 manifest 另記每個輸出檔的 SHA-256、版本 manifest 雜湊、是否為舊版快照、警告，以及離線 viewer bundle 雜湊與影片的衍生來源。`VersionContext` 對有 manifest 的版本只承認登記過的產物與來源，每次讀取都核對雜湊，不符時丟出 `VersionCorruptError`。新增 `cellforge/derived.py`：截圖複製到 `.cellforge/derived/vN/snapshots/`，影片依使用者選擇輸出到不進版控的 `TEMP/videos/vN/`（自動建立 `TEMP/.gitignore`），兩者都登記在 `.cellforge/derived/vN.json`，記錄來源雜湊與 render 設定（影片標明仍是 pillow 截圖輪播、是否只有佔位畫面）。截圖與影片只登記到 `build/` 目前鏡像、且 `scene.glb` 雜湊與該版本 manifest 相符的版本，找不到對應版本時拒絕產生。影片匯出只取該版本名下仍存在且雜湊相符的最新影片；從未產生時要求先產生，暫存被清掉時顯示可重新產生，絕不拿其他版本的影片頂替。匯出端點改為 `async def` 並接受 `version`，前端匯出按鈕傳入目前選取的版本並顯示缺件；新增 `GET /api/projects/{p}/versions/{v}/manifest` 回傳版本 manifest 與衍生檔可用性，版本清單另回傳 `complete`、`level`、`engineering_status`。Astra 違規還原改為還原執行前 `build/` 對應的版本。

理由：開發書 P0 要求影片以不可變版本來源建立衍生 artifact、缺該版本影片時明確要求產生、清除暫存後不能顯示仍可下載，且不覆寫已封存快照。把晚產生的檔案放在版本目錄外並逐一驗證雜湊，既保留「vN 不可變」，又能讓同一版本在日後補產截圖與影片；逐項列缺件則讓 v2 以後尚無影片的版本仍能交付其他內容，同時不會把缺件當成完成。

## D-032：intake → first_build 前置狀態、job 成功判定與可終止的代理子程序（2026-09-28）

問題：`POST /build` 只檢查 `questions.yaml` 沒有 open 問題，範本的空清單直接放行，因此 intake 失敗後仍能啟動 first_build（D-028 的驗收即是如此）；輸入在 intake 後被補充也不會察覺。first_build 的成功條件只是「`.cellforge` 內有任何版本」，案子已有 v1 時，代理即使沒有建置也會被判成功。取消 job 時只結束 Claude CLI 本身，它啟動的 bash、`cell build` 仍在背景執行，可能在取消後發布版本；本機模式的 `_local_build` 以 `subprocess.run` 在執行緒中執行，完全無法取消。另外 WPAC 驗收案 `85c13511b6ea` 的 intake 其實已通過驗證，卻因平台自己的 `git add` 遇到 dubious ownership（log 顯示代理改用 `safe.directory='*'` 才能提交）而整個 job 被判失敗。

處置：
- 每次 intake 結束（成功、失敗、取消）都寫入 `analysis/intake_state.json`，記錄 job、模式與輸入證據指紋（`inputs/manifest.yaml` 各檔路徑與 SHA-256）。成功還須同時滿足：`intake.md`、`checklist_map.md`、`questions.yaml` 都在本次工作中重新產生，舊檔不能冒充；草案通過子程序 `cell validate`；工作期間輸入未被修改。
- first_build 的路由與 worker 開始時都要求：最近一次 intake 成功、指紋與目前輸入相同、正式代理模式下 intake 也必須是正式代理產生（依使用者選擇拒絕離線 intake）。另新增 `POST /builds/manual` 與前端「手寫資料建置（非代理驗收）」按鈕，不經代理直接以目前 YAML 建 L1，結果固定標 `agent_acceptance: false`。
- 版本 manifest 新增 `build.origin` 與 `build.job_id`，由 job 經環境變數傳給代理與建置子程序。first_build／手寫建置成功只看 `job_id` 等於自己的版本：必須存在、為 L1，並通過子程序 `cell version verify`（manifest schema、全部產物／來源／庫模組雜湊、產物清單與 manifest 完全一致、Timeline／Checks schema、GLB 節點、OCP 重讀 STEP）。代理回報的版本號與實際不符時以 manifest 為準並記警告。`agent_acceptance` 只有在 intake 與 first_build 都由正式代理完成時為真。
- 工程代理的總期限（預設 1800 秒）涵蓋所有重試；只有網路或服務端錯誤（連線拒絕、重設、DNS、Connection error、overloaded、503／529 等）會重試，最多三次、間隔 10／30 秒；代理自己回報的失敗（例如幾何）、非網路的崩潰與逾時都直接回報。視覺判讀維持每張 60 秒，逾時或網路錯誤時重試一次。
- 新增 `cellforge/procutil.py`：Windows 以 Job Object（KILL_ON_JOB_CLOSE）、POSIX 以獨立 process group 綁住代理、Astra 與 `cell` 子程序的整個家族；取消或逾時即整族終止，主程序結束後殘留的背景後代也在工作結束時一併收掉。以 returncode 判斷主程序結束、限時讀完剩餘輸出，不依賴管線關閉。
- 已完成工作之後的 git 提交失敗（含 JobRunner 的 log 提交）一律記為 job 警告並顯示於前端，不改判失敗；平台的 git 指令加上只限該案路徑的 `safe.directory`，錯誤訊息附 git stderr。

理由：開發書 P0 要求「失敗或過期 intake 不得誤當成功」「任務成功必須確認本次 job 的新版本、完整 manifest、schema 與幾何回讀」「重試要有次數與總期限、取消可終止子程序、網路失敗可重試、幾何失敗回報具體原因」。以 job id 綁定版本，比「有沒有版本」或「代理說成功」更能排除假成功。實作時發現兩個 Windows 行為：asyncio 的 `Process.wait()` 要等所有持有輸出管線的後代結束才返回，後代成為孤兒時會無限期卡住；`.venv\Scripts\python.exe` 是啟動器，會把真正的直譯器放進自己的 Job Object，讓「只殺父程序」在測試中看似成功。因此測試改以基底直譯器啟動，並確認把終止機制削弱為只殺父程序時三個程序家族測試都會失敗。已知限制：Windows 上 Job Object 建立失敗時退回 `taskkill /T`，無法涵蓋已失去父程序的後代。

## D-033：無人值守的工程代理不得繼承外層工作階段，也不得把工作交給背景子代理（2026-09-28）

問題：DEV-006 第一次正式驗收（案 `軍規筆電_QC_線_P0驗收_20260928_01`）中，intake job `0a0655d64286` 以正式代理一次完成（Check List 73/73、12 個問題），但 first_build job `0b2fb996724d` 在建出兩個 L1 版本（v1、v2，各 71 red）後，代理把「修正干涉並重建」交給背景子代理（Agent 工具），自己回覆「代理完成後我會收到通知」即結束回合。headless（`-p`）模式在最後一則訊息後就結束，背景子代理與其中斷的建置隨工作一起被終止，沒有最終 JSON，平台正確判為失敗，也沒有把 v1、v2 算成本次成功。驗收前另發現：伺服器若從 Claude Code 工作階段內啟動，代理會繼承 `CLAUDECODE`、`CLAUDE_CODE_SESSION_ID`、`CLAUDE_CODE_CHILD_SESSION`、訊息通道 token 與 `CLAUDE_EFFORT=xhigh` 等父工作階段標記。

處置：工程代理啟動前濾掉父工作階段標記，保留授權與一般設定（例如 `CLAUDE_CODE_GIT_BASH_PATH`、`ANTHROPIC_*`）。主工程工作階段加上 `--disallowedTools Agent,Task,TaskOutput,TaskStop,Workflow,Monitor,ScheduleWakeup,CronCreate,RemoteTrigger`（已以實際 CLI 確認這些工具不再出現在可用清單），共通 prompt 明訂這是無人值守執行、不得使用子代理、背景指令或「之後會收到通知」的模式，所有修正必須在本工作階段同步完成，無法在期限內收斂時回傳 `failed` 與剩餘紅項。第一次驗收的失敗結果與日誌原樣保留，重新建立新驗收案重跑 intake 與 first_build，不在失敗案上接續。

理由：D-004 的設計是單一、有期限、可取消的工程工作階段；背景子代理讓工作在回合結束後才繼續，既違反 headless 的生命週期，也讓 D-032 的「以 job 綁定版本、整族終止」失去意義。父工作階段標記則會讓代理與外層工作階段混在一起，effort 等設定也可能不是平台指定的值。

## D-034：first_build「建置成功」與「工程通過」分開判定（2026-09-28）

問題：DEV-006 第二次正式驗收（案 `軍規筆電_QC_線_P0驗收_20260928_02`，first_build job `de52abd7d373`）與隔離缺模組重跑（job `e9b3a7fc55d9`）都已發布通過回讀驗證的 L1 版本（v3：red 65；v2：red 102），代理卻以「紅項未達 0」回報 `failed`，job 因此失敗。原因之一是 D-033 加入共通 prompt 的「期限內無法收斂就回傳 failed」，把「仍有紅項」與「做不出有效版本」混為一談；這與開發書 P0「版本完成狀態、工程檢查結論與匯出完成狀態分開：建置成功不代表工程全數通過」及第 8 節「檢查為紅色或未評估時仍可匯出清楚標記的草案」相衝突。

處置：依使用者選擇釐清契約。共通 prompt 改為：在期限內持續降低紅黃項、不得隱藏或改寫檢查；只要已發布經驗證的 L1 版本（目前最佳工程草案）就回傳 `ok`，並在 summary 逐項列出剩餘紅項與可能原因；只有完全無法發布有效版本（驗證或建置錯誤、無法提供必要模組）才回傳 `failed`。first_build 與手寫資料建置的 job 結果新增 `engineering_status`（取自版本 manifest），未通過時以 job 警告明示「僅可作為草案，不是工程驗收」，前端完成訊息同步顯示；`cell version verify` 另回傳 manifest 的工程摘要。`agent_acceptance` 只代表「正式代理產物」，不代表工程通過。兩次代理自評失敗的 job 與日誌原樣保留，並以第二次的正式 intake 結果重跑 first_build（正式與隔離缺模組各一次）。

理由：job 狀態回答的是「這次工作有沒有做完並產出可追溯的版本」，工程結論回答的是「設計是否可行」。把兩者綁在一起，會讓仍需人工複核的草案無法交付討論，也讓代理為了變綠而傾向修改檢查；分開判定並強制明示，才符合「不可標記為工程驗收完成」與「人工接受的風險不得把紅色改成綠色」的規則。

## D-035：直線規劃遇到 IK 跳解即停止推導，帶號距離改用 collide＋GJK，FK 快取常數（2026-09-28）

問題：D-034 之後的兩次 first_build 重跑（job `d6cd2423db16`、`37e4bd01ef8f`）都在 1800 秒總期限被終止；代理本身正常迭代，但有些 `cell build` 單次就跑 15 分鐘以上。以保存下來的凍結來源重現後找到兩個引擎缺陷：
1. 未指定時長的 `linear: true` 移動會依關節速度反覆拉長時長再重新規劃（最多五輪、每個取樣點解一次 IK）。路徑在 IK 解支之間跳躍時，取樣越密「所需時長」越大，永遠不會收斂：`S3.approach_left` 實測 29→404→5594 秒、取樣 294→4046→55942 點，第五輪將達數十萬次 IK。
2. python-fcl 的帶號距離（`enable_signed_distance=True`，GJK＋EPA）在兩個凸體恰好面貼面時於原生程式碼內無限迴圈且持有 GIL：擷取到的配對是治具頂板與翻面後的 `workpiece.cover_hdd`，旋轉帶 1e-11 級誤差、以約 2e-8 mm 深度貼合。前 8061 次查詢正常，這一次永不返回，計時器與背景執行緒都無法中斷。
另外 profile 顯示 IK 殘差的正向運動學每次都用 scipy 重建固定不變的關節原點旋轉，占建置時間約三分之一。

處置：
- 直線規劃每輪時長最多放大 4 倍；取樣加密至少 1.5 倍時，若最大單段關節變化沒有縮小到「前一輪 ÷ √加密倍數」以下（連續路徑應等比縮小、跳解則不變，門檻取兩者的幾何中點），即判定跳解並停止推導，記入 `timeline.path_discontinuities`（步驟、時刻、關節、跳變角度），該步 `ik` 標為 `failed`，reachability 檢查輸出紅項並具體說明「在 t 時刻哪個關節跳了幾度、無法以連續直線到達」。連續路徑的時長推導行為不變。
- `_signed_distance` 不再使用 FCL 的帶號距離：先以 `collide`（MPR）判定並取 contact depth（與 D-014 原本穿透時的做法相同），未碰撞才用不帶號的 GJK 距離；兩者判定不一致時退回世界 AABB，`source` 照舊標明所用方法。
- 關節原點矩陣以 `lru_cache` 快取且設為唯讀、旋轉改用 Rodrigues 閉式解、拓樸順序於建立 Chain 時算好；與舊實作逐元素差異 < 1e-12 mm，FK 快 5.1 倍。
- `Timeline` 新增相容欄位 `path_discontinuities`，重新輸出 `docs/schema/timeline.schema.json`。
- 碰撞寬相改為每個取樣時刻以 numpy 一次算出所有零件配對的 AABB 間距（公式與原逐對 `_aabb_distance` 相同、候選順序與原巢狀迴圈相同）；profile 顯示逐對版本在約 200 個零件時呼叫 5981 萬次、占 L1 建置八成以上時間。同一份凍結來源的 L1 由 173.5 秒降為 33.0 秒，229 個檢查項目與評估配對數完全相同。`checks.json.engine.collision` 標籤改為 `fcl-collide-depth-gjk-distance-20ms` 以如實反映算法。

理由：開發書 P0 要求「幾何失敗須回報具體原因，不無限盲試」，WP-A/C 第 6 項要求 L1 建置 < 90 秒。跳解不是時間不夠，拉長時長無助於可行性；卡死的帶號距離則讓任何上層期限都只能整個終止建置。兩者都以可解釋的量測結果取代無界的計算，且不改變正常情況下的檢查數值來源。測試分別以擷取到的真實卡死配對（子程序限時，修正前逾時、修正後 2 秒內且帶號結果與幾何構造一致）、注入跳解與平滑高速兩種 IK 解支驗證因果。

## D-036：廠商模型由原廠檔決定鏈與外形；法蘭與 TCP 是鏈上的固定 link；近似由模組自我宣告（2026-09-28）

問題：DEV-007 要求 vendor adapter 實際讀取 URDF、STEP／mesh、frame、關節限制與碰撞幾何，只有 STEP 時不得宣稱關節，近似 stub 須在 UI、檢查與報告標示。實作時發現既有流程有下列落差：
1. `build/modules.py` 的 vendor 分支不論有無原廠檔都載入 `library/robot_stub.py`；`Chain.from_urdf` 只給運動鏈，外形與碰撞沒有來源。
2. GLB、碰撞與取樣假設根 link 叫 `base`／`link0`、每個 link 都有外形、固定關節只出現在末端；原廠 URDF 的 `world`、`base_link`、`tool0` 與夾在活動關節之間的固定關節都會失敗或放錯位置。
3. `SceneModel.resolve_frame` 的 `flange` 沿用 robot_stub 語意（xyz 為靜止姿態下的 base 座標），套到「相對某個 link 宣告」的原廠法蘭會算錯。
4. Getac 範例的手臂直接寫 `part: library/robot_stub.py`，不經 vendor 條目，只看 vendor `approximated` 旗標的標示完全碰不到它。
5. URDF `continuous` 關節若帶只有 velocity 的 `<limit>`，會讀成 ±inf 限位；GLB extras 無法序列化。
6. 驗收（`docs/DEV007_ACCEPTANCE.md`）時發現：原廠鏈的 J6 →（固定）flange（無外形）→（固定）tool 讓碰撞相鄰判定認不出「工具裝在 J6 上」，兩者貼合被判紅（−0.020 mm）；公開 URDF 沒有額定負載，而負載檢查在 `payload_kg` 缺少時直接略過，夾持時會變成沒有任何提示。

處置：
- 新增 `cellforge/vendor_model.py`。有 URDF 時：鏈取自 URDF（公尺／弧度換算）；各 link 的 visual 與 `<collision>` 取自 mesh（STL／OBJ／DAE，DAE 以新增相依 pycollada 讀取）或 box／cylinder／sphere；缺 `<collision>` 時保守地以外形代替。GLB 與碰撞直接使用原始三角網格；STEP 用 `BRepBuilderAPI_Sewing` 產生 faceted 外形，以網格位元組 SHA-256 快取於 module cache 的 `vendor-brep/`。每個 link 超過 50,000 三角面即拒絕並要求輕量網格，不在建置時默默簡化。網格引用只能解析到案子目錄內。
- 只有 STEP／STL／OBJ 時為靜態模組：沒有 chain 與 axes、建置警告「不能作為手臂 actor」，流程把它當 move_to actor 時驗證失敗。
- 登記的法蘭（link＋偏移）成為鏈上的固定 link `flange`，TCP 沿其 +Z 為固定 link `tool`；GLB 節點、取樣、碰撞零件與 frame 解析都由同一條 FK 給出。URDF 已有同名 link／關節時拒絕（URDF 本身就有零偏移的 `flange` link 且被登記為法蘭時直接沿用）。robot_stub 既有的 flange 語意不變。未宣告法蘭時暫以末端 link 原點並發出警告。工具模組的 TCP 改取 `module_definition(params)`。
- GLB／碰撞／取樣泛化為依拓樸順序處理所有活動與固定關節，根 link 取鏈的 `base_link`；手臂鏈上沒有外形的 link 合法。碰撞相鄰判定把「經固定關節剛性相連的父 link」視為同一剛體（J6 ↔ tool 相鄰），但工具與前一節（J5）仍然檢查；robot_stub 鏈的配對不變。
- `cell vendor add-urdf`：URDF 與每個網格逐檔記錄 SHA-256，URDF 引用的網格必須全部提供；`units_in_file` 新增 `m`。專案驗證與建置轉接器兩層都比對雜湊，原廠檔被改動即失敗。vendor 條目沒有原廠檔又沒標 `approximated` 時不再默默改用 stub，而是要求 `cell vendor stub`。
- `ModuleMeta.approximated`（robot_stub 設為真）與 vendor `approximated: true` 都讓模組標為近似：建置警告、版本 manifest `modules[].model_source／approximated`、GLB extras、檢查項目 `approximated_models` 與 `source` 附註、前端檢查面板提示、報告段落。Getac 範例因此多兩則建置警告，原本斷言「警告為空」的測試改為斷言只有這兩則。
- 版本凍結的 library 只在 vendor 條目為近似（或讀不到條目）時才納入 `robot_stub.py`，原廠模組的版本不再宣稱依賴它。
- `continuous` 關節依 URDF 規範忽略 lower／upper。手臂沒有 `payload_kg` 而實際夾持時，負載檢查輸出黃色「未評估」。
- `CheckItem` 新增 `approximated_models`、`ManifestModule` 新增 `model_source`／`approximated`，重新輸出 `docs/schema/checks.schema.json`、`version-manifest.schema.json`、`vendor-manifest.schema.json`。

理由：開發書 P1 要求「URDF 提供運動鏈，STEP／mesh 提供形狀」「不得因品牌名稱存在便視為真機驗證」，ACC-03 要求移動關節後視覺、FK、碰撞與 frame 一致。讓法蘭與 TCP 成為鏈上的 link，是讓四種表示共用同一條 FK 的最小改動；近似改由模組自我宣告，才能涵蓋不經 vendor 條目的既有案例。依使用者選擇，以 DENSO 公開的 VS-060 URDF（MIT）驗證轉接器，原廠檔只放在驗收案的 `vendor/`；Getac 指定的 VS-087 沒有公開 URDF，維持近似 stub 並標示。

## D-037：單一工件擴充為多零件實例，持有者唯一、由持有鏈連帶移動（2026-09-28）

問題：DEV-008 要求「將單一工件狀態擴充成多 instance；每個零件有唯一持有者、初始位置、安裝關係和組裝狀態；舊單工件案例透過相容載入維持原行為」。既有引擎、排程、取樣、GLB、碰撞、檢查與前端 viewer 約兩百處假設只有一個 id 為 `workpiece` 的工件：`SimulationState` 只有一組 `workpiece_pose`／`attached_to`，viewer 把 `workpiece` 節點名寫死，版本驗證也固定期待 `workpiece` 節點。

處置：
- `workpiece.yaml` 新增 `parts`（每個零件：`id`、`sku` 或 `part` 模組二擇一、`params`、`mass_kg`、`initial.frame`＋`offset`、狀態軸初始值 `state`、`trust`）；`skus` 改為可省略（預設空清單，未刪欄位）。沒有 `parts` 時沿用單一工件 `workpiece`，取 `process.workpiece_sku` 與 `initial_workpiece_frame`。`ProcessStep` 新增 `object`（作用的零件 id），單一工件時可省略。
- 零件外形可以是 SKU 方塊（沿用護蓋與面 frame）或 CadQuery 零件模組（`library/` 或 `parts/`，`MODULE`＋`build(params)`，軸即零件的狀態軸，例如接頭翹起角）；零件模組的 frame 相對於所屬 link，與設備模組同語意。零件 id 不得與模組 id 或 `system` 相同。
- `SimulationState.parts` 記錄每個零件的位姿、唯一持有者與相對持有者的位姿；持有者可以是模組（含致動軸所帶的 link）、手臂 `<robot>.tool`、或另一個零件。手臂關節、模組軸、轉送、翻面移動持有者時，被持有的零件（含零件上再承載的零件）沿持有鏈一起移動並寫入各自的位姿軌跡；母零件轉送帶旋轉時逐點取樣，避免子零件各自內插與 slerp 不一致。初始放置依持有關係排序，專案驗證即拒絕成環的初始持有關係、流程引用不存在的 object、多零件產品省略 object 的零件動作。`state.workpiece_pose` 等舊屬性保留為主工件的相容存取。
- 排程的「同一工件動作依序執行」改為每個零件各自序列化；單一工件時與原規則等價。
- GLB 與 STEP 每個零件一個具名節點／頂層元件（GLB extras `part: true`、`sku`、`mass_kg`、`part_file`）；版本 manifest 新增 `parts`（零件模組記錄雜湊），`cell version verify` 依此驗證節點，舊版本沒有 `parts` 時視為 `workpiece`；多零件的零件模組一併凍結進版本。viewer 對任何帶 `pose_quat` 的時間軸節點套用位姿。
- 碰撞：每個零件各自的碰撞零件；零件放在另一零件上（安裝或承載）時兩者接觸視為支撐，只有超過 1 mm 的穿透才判紅；手臂夾持的零件與該工具排除；模組交接支撐窗口按零件分別計算。負載檢查改為手臂實際持有的零件加上其上承載的零件質量。
- 相容驗證：重構前（HEAD `948bf60`）與重構後各建一次 Getac 範例 L1，`timeline.json` 與 `checks.json` 逐項比對 0 處差異。

理由：以「每個零件一份狀態＋唯一持有者」取代特例，單一工件只是 parts 為一個的情況，後續的取放、插入、壓合動作契約（DEV-008 其餘部分）與 shutter、PCB 多零件案例（ACC-12）都建立在同一套持有語意上；舊案例的輸出逐位不變，才能確保相容載入沒有改變任何既有檢查結論。

## D-038：動作契約組合基本動作並記錄失敗原因；合法接觸只在宣告的窗口、區域、方向與容差內成立（2026-09-28）

問題：DEV-008 要求「可重用的取料、夾持、放置、插入、壓合、檢測動作契約，每個動作明確宣告對象、前置條件、工具、路徑、完成事件及失敗原因」，以及「合法接觸以物件對、接觸區域、方向、時間窗口及容差宣告，不能將壓頭或工件永久從碰撞檢查排除」。既有流程只有 move_to／grip／release 等基本動作，前置條件不成立時不是默默繼續就是整個建置失敗；碰撞檢查只有「驅動護蓋」與「交接支撐」兩種寫死的允許接觸。

處置：
- 新增動作 `pick`、`place`、`insert`（`press`、`inspect` 的 schema 一併定義，於本步驟第三段實作壓合模型與相機視野後開放，在此之前驗證時明確拒絕）。步驟以 `object`（或 `objects`）宣告對象、`tool` 宣告需要的工具模組、`path`（`approach_mm`、`retract_mm`、`depth_mm`、`hold_s`、`speed_scale`）宣告路徑，完成事件沿用 `<步驟>.done`。
- 契約由引擎基本動作組合：pick＝關節移到接近點→直線下探→夾持→保持→直線撤離；place＝移到目標上方（插入時直線）→直線放下（插入再多走 `depth_mm`）→放開並改由目標 frame 的擁有者持有→直線撤離。前置條件不成立時不移動，直接記錄失敗；結果寫入新欄位 `timeline.action_results`（狀態、固定失敗代碼、中文原因、細節如放置誤差與插入對象），檢查新增 `process` 類型逐項列出（完成綠、失敗紅）。失敗代碼：`HELD_BY_OTHER`、`TOOL_OCCUPIED`、`WRONG_TOOL`、`NOT_HELD`、`TARGET_OCCUPIED`、`UNREACHABLE`、`MISALIGNED`。
- `process.yaml` 新增 `contacts`：`pair`（模組、link 或零件）、`window`（步驟 id）、`tolerance_mm`、選填 `region`（frame＋XY 矩形）與 `direction`（pair[0] 相對 pair[1] 的接近方向，以區域 frame 表示）。碰撞取樣時，宣告窗口內的穿透若不超過容差、接觸點在區域內（邊界容許 0.5 mm）、接近方向與宣告夾角不超過 30°，即為綠色並標 `contact_id`；任一不符為紅色並寫明原因；窗口外的同一物件對照一般規則檢查。專案驗證拒絕引用不存在物件、區域 frame 或步驟的宣告，以及負的容差。
- 引擎的 `_move_to` 拆出以世界位姿為目標的 `_move_pose`，供契約組合使用；既有行為不變。
- 相容：Getac 範例 L1 與重構前基準相比，除了新增的空欄位（`contact_id: null`、`action_results: []`）外逐項相同。

理由：把前置條件、工具、路徑與失敗原因綁在動作上，工程代理與使用者才能從檢查結果直接知道「哪個動作因為什麼沒做成」，而不是從 IK 失敗或碰撞紅項反推。接觸只以有期限、有位置、有方向、有容差的宣告放行，壓頭與工件在窗口外、區域外或壓過頭時仍會被檢出，符合「不得永久排除」的要求。

## D-039：壓合以受限行程與接觸狀態建模；檢測以相機幾何判定可見性，結果標明來自狀態模型（2026-09-28）

問題：DEV-008 的 SSD 驗收（ACC-04）要求「載盤承載 → 壓頭接近 → 受限壓合 → 撤離 → 相機取像 → 結果展示；PCB、USB 銀腳及壓頭均有獨立可辨識幾何；相機圖中必須看得到檢查目標；故意增加壓入量、移錯治具、抬高相機支架時，對應檢查必須發現問題」。開發書 2.3 也限定「SSD 壓合可先採受限行程及接觸狀態模型，未有材料與試驗資料時不宣稱預測真實變形或接觸力」、「相機可計算幾何視野、遮蔽與取樣解析度；合成畫面上的檢測結果不等於真實影像演算法準確率」。既有平台沒有相機參數、沒有能被壓回的零件狀態，也無法解析手臂工具上的 frame（相機、多個壓墊）。

處置：
- `ModuleDef.cameras`（光學 frame → `CameraSpec`：感光元件像素與像素尺寸、焦距、工作距離、光圈、容許模糊圈）；景深依薄透鏡近似計算，解析度以針孔模型換算 mm/px。場景可解析手臂工具模組上的 frame 與相機（`robot_1.camera`、`robot_1.pad_3`：tool link · TCP⁻¹ · 工具 frame）；工具模組設 `SEPARATE_COLLISION` 時各子零件分別成為碰撞體（8 個壓墊各自判定）。
- `press` 契約：壓墊 frame 依序對應 `objects`，壓墊沿直線下壓到對位 frame 再多走 `depth_mm`。每個取樣點以二分法求出「壓合面不越過壓墊表面」的最大狀態軸值（接頭翹起角只能往貼平方向減少）；貼平後仍超出的量由壓墊彈簧吸收，超過 `spring_mm` 即過壓。撤離時依零件參數 `rebound_deg` 回彈（示意，只發生在第一次壓合）。失敗代碼 `OFF_TARGET`（壓合面不在壓墊範圍內）、`NO_CONTACT`、`OVERTRAVEL`、`NOT_SEATED`；每顆的壓前／最小／壓後角度與彈簧壓縮量寫入動作結果。不建材料模型、不輸出接觸力。
- `inspect` 契約：手臂相機可用示教點（移 TCP，相機落在工具上實際的位置——支架改變時才會被發現）或 `view`（直接指定相機位姿）；固定相機不移動。取像時逐個 ROI 判定：在影像範圍內、深度在景深內、mm/px 不超過要求、從相機到 ROI 中心與四角的線段不穿過其他碰撞凸包（半空間求交，不增加相依）。可判定時依 `gap_frames` 計算間隙並給 OK／NG；檢查新增 `vision` 類型：無法判定為紅；NG 為紅，但之後同一 ROI 複檢 OK 時標黃「補壓後複檢 OK」；所有判定都註明「來自壓合狀態模型的間隙，不是實拍影像的演算法結果」。
- GLB 為固定相機與手臂工具相機加入帶 `extras.camera`（視角、景深、慣例）的節點；viewer 與 `cell snapshot --cam <相機節點>` 以該相機的位姿與垂直視角出圖。
- 零件模組的 frame 一律以模組座標（靜止姿態）表示並隨所屬 link 移動，與零件品質檢查的包圍盒規則、SKU 零件的舊語意一致；零件的 `params` 保存在建好的零件上供狀態模型使用。
- 碰撞：同一被承載產品組件內的不同零件互相、與最終承載它的模組之間，以及以 `mount` 安裝的模組與其安裝座，都視為支撐（只有穿透超過 1 mm 才算干涉）；接觸宣告的方向改為軸線判定（沿宣告方向接近或原路撤離都合法，橫向滑入才不符）；接觸宣告的物件可用萬用字元。Getac 範例 L1 與重構前基準相比仍只差新增的空欄位。
- 新增範例 `examples/ssd_press/handwritten`（配方 usb-2x8）：案內零件 USB-A 接頭、2×8 連板、載盤、8 頭壓墊＋45° 斜視相機工具、全局相機皆通過零件品質檢查；尺寸、翹起角與回彈取自 TestCode 照片目測並列為 inferred 假設與待確認問題；手臂為 VS-068 型錄近似（依使用者選擇）。建案時會一併複製範例的 `parts/`。

理由：用可解釋的幾何與行程限制表達「壓到哪裡、壓多深、有沒有壓過頭、相機看不看得到」，每一種失敗都對應到可修正的工程量（壓入量、治具位置、相機位置），又不越界宣稱力學或影像演算法的準確度。示教點與「由相機位姿反推」兩種取像方式並存，是因為只有前者能反映「硬體改了、程式沒改」這類現場常見的錯誤。

## D-040：成本由 costing.yaml 與模組實例計算；缺價不計入、組件與子件不重複計價、公式與捨入明示（2026-09-28）

問題：開發書 P2／DEV-009 要求採購 BOM、成本模型、XLSX／CSV 匯出與網頁摘要，驗收 ACC-05「改數量、單價、工時及缺價 → 成本依公式更新，缺價單獨列出，不重複計價」，並要求以獨立小型人工核算案例驗證總額。既有平台只有 `exports.py::_bom` 列出模組清單，沒有單價、工時、匯率、公式或版本化的成本結果。

處置：
- 新增 `costing.yaml`（`cellforge/schema/costing.py`，輸出 `docs/schema/costing.schema.json`）：採購項型錄（種類：模組／採購件／加工件／耗材／服務；子系統、型號、規格、供應商、單位、單價、幣別、來源、報價日期、有效期、可信度、等級與 ±幅度、適用範圍、組件）；設備對應 `equipment`（依 cell.yaml 模組的 part／vendor／module／手臂工具選出實例，每個實例各計一次）；不隨設備增減的固定 BOM 列（`for` 標示所屬模組）；工時費率與工時項目（分類：機構、電控、軟體、裝配、配線、調試、驗證、文件、POC、管理、其他）；匯率（日期與來源）；計算政策（管理費率、預備費率、稅率、捨入、計價）。金額、數量與比率一律十進位，YAML 小數經字串轉換。凍結版本時一併凍結 `costing.yaml`。
- 計算（`cellforge/costing/calc.py`）：組件有單價時子件不另計，待報價時展開子件；同一採購項對同一模組被兩個來源計入即報 `DUPLICATE` 並只計一次，有單價的組件與其子件對同一模組同時計入報 `ASSEMBLY_DOUBLE_COUNT`；同料合併成一列採購數量並保留每個來源。單價 null、缺匯率或單位不符的列不計入已知成本，列入缺價清單與覆蓋率，`complete: false` 時總額標為「已知成本小計」；報價過期為警告。公式：材料 = Σ(數量 × 單價 × 匯率)、人工 = Σ(工時 × 費率 × 匯率)、管理費 = 率 × (設備 + 開發)、預備費 = 率 × (設備 + 開發 + 管理費)、成本合計 = 四者和、稅 = 稅率 × 成本；計價 `margin`（售價 = 成本 ÷ (1 − 毛利率)）或 `markup`（售價 = 成本 × (1 + 加價率)）擇一，未設定時只出預算（依使用者選擇）。捨入：每列小計到 `line_decimals`，管理費、預備費、成本合計、稅額與售價到 `total_decimals`，預設四捨五入。上下限為逐列 ±幅度加總，不是信賴區間。
- 建置時有 `costing.yaml` 即產生版本產物 `costing.json`（版本回讀驗證其版本號），資料錯誤併入建置警告；`GET /api/projects/{p}/versions/{v}/costing` 只讀該版本快照。匯出新增 `costing`（XLSX：摘要、採購明細、工時、設備對應、子系統彙總、缺價清單、問題、版本；參數格可改、小計與總額以公式計算並附程式計算值對照）與 `purchase_bom`（合併同料的採購 BOM CSV）；「全部」匯出只在版本有成本資料時包含這兩種，沒有成本資料的案子不會因此變成不完整。前端新增「成本」分頁。由範例建案會一併帶入範例的 `costing.yaml`。
- 驗證：獨立人工核算案例（期望值在測試中逐步手算）、增刪相機與改單價的因果、缺價不當 0、重複計價與組件雙計、缺匯率／單位不符／報價過期、毛利率與加價率公式；SSD 範例的總額與 TestCode 成本試算表逐項一致，並以 Excel 重算 XLSX 公式與程式值 0 處不一致。

理由：設備數量由模組實例推導、固定列另標所屬設備，增刪設備才會同步而不留下重複成本；缺價、缺匯率與單位錯誤一律明示而不是補 0，是「不能把缺價當免費」的最直接保證。公式、捨入階段與上下限的性質都寫進結果與 XLSX，讓人工可以逐格複核。工程代理產生成本草案依使用者選擇留待後續（例如 DEV-014 案例遷移時一併接上）。

## D-041：電控以端子連通圖建模；設備樣板依模組實例展開、I/O 由點位池配置，連接檢查併入 L1 證據（2026-09-28）

問題：開發書 P3／DEV-010 要求連接圖涵蓋器件、端子、電源域、保護器件、負載、I/O 與通訊節點，製程使用的感測器、致動器、相機、燈源、馬達與控制器都要連到電控器件 id，並檢查電位、端子型別、電壓與訊號相容；驗收要求「刪除供電連接必須產生斷路或缺接線檢查」「重複 I/O 位址、錯誤電壓域與不存在的端子都要被發現」，ACC-06 要求「加相機、改 I/O、刪供電連接 → 3D、BOM、圖面與連接檢查同步變更」。既有平台沒有任何電控資料。

處置：
- 新增 `electrical.yaml`（`cellforge/schema/electrical.py`，輸出 `docs/schema/electrical.schema.json`）：電位網 `nets`、器件 `devices`（種類、型號、`catalog_ref`＋`catalog_quantity` 對採購項、`module_ref` 對 3D 模組、盤內／現場、外形、軌道位置、額定值、端子、內部導通 `bridges`、trust）、連接 `connections`（端點為 device＋terminal、net 或 pool 三擇一，線號、線材）、點位池 `pools`、I/O 表 `io`（固定位址或由池配置，經端子排 `via` 到現場端子）、設備樣板 `equipment`（依 cell.yaml 模組實例的 part／vendor／module／tool 比對，每個實例以 `{module}` 代換產生器件、連接與 I/O）、安全回路 `safety`、盤面 `panel`、圖框 `drawing`。端子的 `voltage` 是電位域名稱（24VDC、0V、AC-L、AC-N、PE…），不是數值。未加引號的數字端子名稱視為字串。凍結版本時一併凍結 `electrical.yaml` 與 `drawing_templates/`。
- 配置規則（依使用者選擇「設備樣板＋自動配置」）：手動指定的位址與端子排位置先佔用，自動配置依池內順序取第一個空點位，永不覆蓋手動點位；同一端子被兩處使用報 `DUPLICATE_ADDRESS`，池用盡報 `POOL_EXHAUSTED`。I/O 本身展開成接線：控制器通道 →（端子排）→ 現場端子，盤內線與現場線共用線號。
- 引用錯誤（不存在的器件、端子、電位網、點位池、軌道、模組，或 I/O 位址不是通道器件的端子、樣板 id 衝突）一律使專案驗證失敗，不進入檢查；LOGO 只接受案內 `drawing_templates/` 的 PNG／JPG／SVG。
- 連接檢查（`cellforge/electrical/checks.py`，項目 `CHK-ELEC-*`、`type: electrical`，`CheckItem` 新增 `status`：pass／fail／not_evaluated／error 與 `code`）：以聯集尋找把接線、電位網與器件內部導通合成連通群組。
  - 必要端子本身沒有接線為「缺接線」（內部導通不能代替進線端）。
  - 受電端子要追到同電壓域且本身有電的供電端子。電源器件的輸出只有在它的受電端子都有電時才算有電，以不動點迭代求出；因此斷 AC 支路時 24 V 負載也連帶失電。追不到來源為「斷路」，只接到其他電壓域為「電壓域錯誤」，同一群組同一電壓合併成一項並列出受影響端子。
  - 其他檢查：
    - 電源端子與電位網電壓不符。
    - 同一群組混用不相容訊號（電源、接地、數位、安全、類比、網路、現場匯流排、序列、原廠專用）。
    - 製程使用的模組（手臂、相機模組、手臂工具相機、非等待動作的 actor）沒有對應 `module_ref` 的器件（相機要求 kind=camera）。
    - 盤面排版的軌道寬度溢出與上下間距不足（排版幾何與盤面圖共用）。
  - 電源與負載額定值齊全才評估容量，否則為黃色 not_evaluated（不以預設值推定合格）。安全回路一律黃色 not_evaluated「未完成風險評估與安全架構驗證；不宣稱安全等級或停止類別」。
  - 有成本資料時，器件 `catalog_quantity` 加總與採購數量不一致、或採購項不存在，為黃色提示；`catalog_quantity: null` 表示含於組套，只核對採購項存在。
- 建置時有 `electrical.yaml` 即產生版本產物 `electrical.json`（展開後的器件、接線、I/O 表、點位池使用、模組對照、必須接電控的模組清單與檢查，版本回讀驗證版本號）；L1 時檢查項目併入 `checks.json` 並重算摘要。由範例建案會帶入範例的 `electrical.yaml`。
- SSD 範例的電控資料由 TestCode `circuit-data.json`（P02）轉入（依使用者選擇）：
  - 保留原器件代號、I/O 點序、端子排位置與線號。
  - 以下為推估：供電以 L／N／PE 電位域表示、IO1 為 16 DI／16 DO、SW1 為 8 埠、IPC1 為 4 埠 GigE PoE、急停與門互鎖為雙通道規劃回路。
  - TestCode 未列點位的頻閃觸發與固定相機觸發，由 DO 點位池配置。
  - 全部標 inferred，並列入 A-SSD-ELEC／SUPPLY／PANEL／SAFETY／TRIGGER 與 Q-SSD-E01～E06。
  - 固定相機 `global_camera` 以設備樣板產生，新增同型相機模組即自動多一台相機器件、一個影像埠、一個觸發點位，與成本的相機數量同步。

理由：以端子為節點的連通圖，同時承載供電、訊號、安全與網路，缺接線、斷路、電壓域與訊號相容都能從同一張圖判定，且每個結論都能指到具體端子。供電有電與否以不動點求出，才能反映「上游斷線、下游全部失電」的實際因果。設備樣板加點位池讓 3D 模組增減時電控、I/O 與 BOM 一起變化；手動點位優先且必查重複，則保留工程師對既有點序的控制。額定值與安全等級缺資料時只標未評估，不以預設值或圖面外觀宣稱合格。圖面（PDF／SVG）與前端電控分頁在本步驟後續兩段完成。
