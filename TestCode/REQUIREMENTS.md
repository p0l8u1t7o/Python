# 環境需求與安裝

clone 之後執行一次：

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1          # 檢查必要環境＋快速檢查
powershell -ExecutionPolicy Bypass -File setup.ps1 -All     # 另外建立 Python 環境、下載 ffmpeg
```

## 必要（3D 展示、開發、檢查）

| 項目 | 版本 | 用途 | 安裝 |
|---|---|---|---|
| Node.js | 22 以上（開發機 24.21，CI 用 22） | 本機伺服器、統一檢查、截圖、Pages 建置；**不需要 npm 套件** | `winget install OpenJS.NodeJS.LTS` |
| Chrome 或 Edge | 近期版本 | 瀏覽器檢查（`ui-check`、`shots`、各專案 browser 檢查）用 DevTools Protocol 驅動無頭瀏覽器 | Windows 內建 Edge 即可；其他路徑設環境變數 `CHROME_PATH` |
| Git | 任何近期版本 | 版控；回歸比對用 `git worktree` 拍基準截圖 | `winget install Git.Git` |

three.js 已放在 `core/vendor/`，不需要網路或套件管理器。

## 選用（只有特定工具需要）

| 項目 | 需要的工具 | 安裝 |
|---|---|---|
| Python 3.12＋`requirements.txt` | 錄影稽核與驗證（`tools/movie-export`）、影片驗證（`MilitaryGradePC/tools/verify_video.py`）、電路圖（`tools/circuit-drawings`）、成本估算表、`core/tools/compare-review.py` | `setup.ps1 -Python`（建立 `.venv` 並安裝） |
| ffmpeg／ffprobe（支援 NVENC 的 Windows 版） | MP4 錄影輸出（`tools/movie-export/server.py`、`MilitaryGradePC/tools/render_server.py`、影片驗證） | `setup.ps1 -Ffmpeg` 下載到 `MilitaryGradePC/tools/bin/`（不進版控）；也可用 `-FfmpegZip <本機 zip>` |
| 中文 TrueType 字型 | 電路圖 PDF（reportlab） | 預設 `C:/Windows/Fonts/msjh.ttc`（微軟正黑體）；其他字型設 `CIRCUIT_FONT` |
| poppler `pdftoppm` | 電路圖驗證時把 PDF 轉成 PNG（`tools/circuit-drawings/verify.py --render`） | 安裝 poppler 後設 `PDFTOPPM` 指向 `pdftoppm.exe` |
| `@oai/artifact-tool`（Node 套件） | `WorkpieceMeasurement/tools/update_cost_estimate.mjs` 更新既有 XLSX | 非公開套件，沒有就不能用這支更新器；成本表本身在本機 `docs/`，不進版控 |

## 環境變數

| 變數 | 用途 | 預設 |
|---|---|---|
| `CHROME_PATH` | 指定瀏覽器執行檔 | 依序找 Chrome、Edge 的標準安裝路徑 |
| `UI_PORT` | `check.mjs` 內建 `ui` 檢查用的 port（平行跑檢查時錯開） | 8771 |
| `CIRCUIT_FONT` | 電路圖字型 | `C:/Windows/Fonts/msjh.ttc` |
| `PDFTOPPM` | poppler 的 pdftoppm | （無，需要時指定） |
| `NODE_BINARY` | 成本估算表包裝程式用的 node | PATH 上的 node |

## 常用 port

| port | 用途 |
|---|---|
| 8770 | `node core/tools/serve.mjs`（本機展示首頁，各專案 `run.bat` 也用它） |
| 8771 | `check.mjs` 的 `ui` 檢查（`UI_PORT`） |
| 8790 | `shots.mjs` 預設（`--port` 可改） |
| 8782／8783 | 錄影輸出伺服器（`tools/movie-export`） |

## 不進版控的東西

- **各專案的 `docs/`**：使用者提供的圖面、照片、影片、規劃與成本資料，只留本機。新專案也要把 `docs/` 加進 `.gitignore`。
- **`TEMP/`、`LOGS/`、`*.log`、`.venv/`、`_site/`**：本機產物。
- **ffmpeg 執行檔**：由 `setup.ps1 -Ffmpeg` 下載。
