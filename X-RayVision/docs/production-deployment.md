# 產線化：帳號權限、授權、更新退版與安裝部署　技術規格

| 項目 | 內容 |
|---|---|
| 文件編號 | SPEC-005 |
| 版本 | v1.0 |
| 日期 | 2026-09-23 |
| 對應規劃書 | PLAN-001 第 8.1、11、12 節與第 10 節第 4 階段 |
| 相關文件 | 操作手冊 [MAN-001](operation-manual.md)、服務與資料 [SPEC-003](service-and-data.md)、使用者介面 [SPEC-004](user-interface.md) |

本文件說明第 4 階段完成的產線化功能與原廠端發行作業。客戶端操作步驟見操作手冊。

---

## 1. 第 4 階段決議（2026-09-23）

| 事項 | 決議 |
|---|---|
| 安裝形式 | 標準安裝程式 setup.exe（Inno Setup），含執行環境與前端，不需另外安裝 Python 或 Node.js |
| 執行方式 | Windows 服務，開機自動啟動（延遲啟動），不需登入 Windows |
| 帳號 | 產品內建帳號，與 Windows 帳號無關；三種角色 |
| 資料保留 | 預設不自動刪除；磁碟剩餘空間低於門檻時警示；系統管理員可設定封存影像保留天數 |

---

## 2. 帳號與權限

### 2.1 角色

| 權限 | 操作員 | 工程師 | 系統管理員 | 內容 |
|---|:-:|:-:|:-:|---|
| view | ● | ● | ● | 總覽、紀錄、影像、配方、工作、監看狀態 |
| import | ● | ● | ● | 上傳影像、重新分析、取消／重新執行工作 |
| review | ● | ● | ● | 人工複判 |
| import_path | | ● | ● | 以本機路徑匯入 |
| recipe_edit | | ● | ● | 建立、修改、發布、停用配方 |
| watch_manage | | ● | ● | 管理監看資料夾 |
| diagnostics | | ● | ● | 匯出問題回報包 |
| audit_view | | ● | ● | 檢視稽核紀錄 |
| user_manage | | | ● | 帳號管理 |
| settings | | | ● | 系統設定、資料保留 |
| license | | | ● | 授權 |
| update | | | ● | 軟體更新與退版 |

權限表定義於 `xrayvision/service/auth.py` 的 `PERMISSIONS`；後端每個端點逐一檢查，前端只依權限隱藏選單與按鈕。

### 2.2 帳號安全

| 項目 | 設定 |
|---|---|
| 首次使用 | 資料庫沒有任何帳號時，網頁進入「建立系統管理員」畫面；建立後此功能關閉 |
| 密碼 | 至少 8 個字元；scrypt（N=2^14, r=8, p=1）加鹽雜湊，不儲存明文 |
| 首次登入／重設後 | 必須先變更密碼才能使用其他功能 |
| 登入失敗 | 連續 5 次失敗鎖定 5 分鐘；系統管理員重設密碼時一併解除 |
| 工作階段 | HttpOnly Cookie `xrv_session`（SameSite=Strict），閒置 12 小時失效；帳號被停用、變更角色或由管理員重設密碼時，該帳號所有工作階段立即失效 |
| 最後一位管理員 | 不可停用或降級最後一位啟用中的系統管理員 |
| 本機救援 | `python -m xrayvision reset-password <帳號> --data <資料目錄>`：產生一次性密碼、解除鎖定並重新啟用；需可寫入資料目錄（Windows 系統管理員），稽核操作者記為 `local-console` |

### 2.3 稽核

所有寫入操作以登入帳號記錄於稽核紀錄（資料庫觸發器保證只能新增）。第 4 階段新增的動作：`auth.login`、`auth.logout`、`auth.login_failed`、`user.*`、`license.request`、`license.import`、`license.deactivate`、`settings.update`、`maintenance.purge_archive`、`update.staged`、`update.rejected`、`update.requested`、`update.rollback_requested`、`system.update_failed`、`system.rollback`、`system.archive_import`。啟動器在服務停止期間直接寫入資料庫，操作者記為 `launcher` 或發出請求的帳號。

---

## 3. 資料保留與磁碟空間

| 設定 | 預設 | 說明 |
|---|---|---|
| `retention_days` | 未設定（不自動刪除） | 設定後，每小時刪除超過天數的**封存影像檔**；檢測紀錄、結果、疊圖座標與稽核紀錄全部保留，影像標記為已清除（`images.archive_purged_at`），檢閱畫面顯示「影像檔已不存在」 |
| `disk_warn_gb` | 20 GB | 資料目錄所在磁碟剩餘空間低於此值時，所有登入者可見警示橫幅 |

設定存於資料庫 `settings` 資料表，由「系統管理」頁修改（`PUT /api/settings`）。系統管理員也可立即執行一次清除（`POST /api/maintenance/purge`）。

---

## 4. 軟體授權實作

### 4.1 檔案

| 檔案 | 位置 | 說明 |
|---|---|---|
| 安裝識別與金鑰 | `<資料目錄>/license/install.json`、`install_key.pem` | 首次啟動產生；每份安裝一組 Ed25519 金鑰，用於簽署申請檔與停用證明 |
| 授權申請檔 | 下載 `license_request_<機器碼>.xrvreq` | 產品、版本、安裝識別、機器碼、硬體特徵雜湊；以安裝金鑰簽章 |
| 授權檔 | 匯入 `.xrvlic` → `<資料目錄>/license/license.json` | 客戶、授權編號、起訖日、寬限天數、可用模組、綁定的安裝識別與硬體特徵；原廠私鑰 Ed25519 簽章 |
| 停用證明 | 下載 `license_deactivation.xrvdeact` | 安裝金鑰簽章；原廠以 `license_admin.py verify-deactivation` 驗證後辦理移轉 |

### 4.2 機器碼

硬體特徵取 MachineGuid、BIOS UUID、主機板序號、CPU 識別碼四項，各自雜湊後保存。比對時容許其中一項變更（例如更換主機板以外的零件或系統更新），兩項以上不符判定為「授權與本電腦不符」。

### 4.3 狀態

| 狀態 | 可分析 | 說明 |
|---|:-:|---|
| valid | ● | 有效；到期前 30／14／7／1 天起顯示提醒 |
| grace | ● | 已到期，在授權檔的寬限天數內；持續顯示警示 |
| expired | | 已到期且超過寬限期 |
| missing | | 尚未匯入授權檔 |
| invalid | | 簽章或格式錯誤、不屬於本安裝 |
| machine_mismatch | | 硬體特徵不符 |
| not_started | | 尚未到授權起始日 |
| clock_tampered | | 系統時間早於授權簽發時間或資料庫最新紀錄時間（超過容許誤差），疑似調回時鐘 |
| deactivated | | 已停用（移轉） |

不可分析時：資料夾監看暫停匯入（檔案維持等待中，恢復後自動處理）、手動匯入與重新分析被拒絕；檢視、報告、匯出、問題回報包、授權匯入與帳號管理仍可使用。發布配方時檢查模組是否在授權範圍內。

### 4.4 原廠端工具

`tools/license_admin/license_admin.py`（不隨產品發布）：

```
python tools/license_admin/license_admin.py keygen --out <目錄>                          產生原廠授權金鑰對
python tools/license_admin/license_admin.py inspect <申請檔.xrvreq>                     檢視申請內容
python tools/license_admin/license_admin.py issue <申請檔> --key <私鑰> --customer "…" --days 365 --grace 14 [--modules bump_alignment] --out <授權檔.xrvlic>
python tools/license_admin/license_admin.py verify-deactivation <停用證明> <原申請檔>
```

每次簽發記錄於 `tools/license_admin/issued.jsonl`（不納入版控，應由原廠另行備份）。

---

## 5. 軟體更新與退版實作

### 5.1 目錄配置

```
C:\Program Files\X-RayVision\              安裝目錄 (XRAYVISION_HOME)
  launcher\launcher.py、launcher.json      啟動器與設定 (資料目錄、連接埠)
  launcher\python\                         啟動器專用執行環境；進版時不替換
  service\XRayVisionService.exe、.xml      Windows 服務包裝 (WinSW 2.12，MIT 授權)
  service\*-service.cmd、service-control.ps1  啟動／停止／重新啟動／查詢服務的腳本
  versions\<版本>\python\                  產品執行環境 (Python 3.12 embeddable＋固定版本依賴)
  versions\<版本>\app\xrayvision\          程式
  versions\<版本>\app\web\dist\            前端
  versions\<版本>\version.json
  current.json                             目前版本
C:\ProgramData\X-RayVision\                資料目錄
  xrayvision.db、settings.json、license\、calibration\、archive\、results\、logs\
  updates\incoming\、updates\requests\、updates\status.json、updates\history.json
  snapshots\<時間>__<來源版本>__<目標版本>\
  rollback_archives\
```

產品執行環境的 `python312._pth` 決定完整模組搜尋路徑（`..\app` 指向同版本的程式）；此模式下 `PYTHONPATH` 無效，各版本互不干擾。

### 5.2 服務

- 服務識別 `XRayVision`，顯示名稱 `X-RayVision Inspection Service`，執行身分 LocalSystem，自動（延遲）啟動。
- 服務包裝程式執行啟動器；啟動器啟動目前版本的平台服務（`python -m xrayvision serve`），監看其狀態，異常結束時依 2、4、8…最多 60 秒退避重新啟動。啟動器本身異常結束時，服務包裝程式於 10／30／60 秒後重新啟動。
- 停止服務：服務包裝程式送出 Ctrl+C 給啟動器，啟動器對平台服務送出 CTRL_BREAK 正常關閉（停止佇列與分析子行程），30 秒內未結束則結束整個行程樹。服務包裝程式的停止逾時為 90 秒。
- 平台服務只綁定 `127.0.0.1:8600`，不需開放防火牆。
- 服務控制腳本：`service\start-service.cmd`、`stop-service.cmd`、`restart-service.cmd`、`service-status.cmd` 呼叫 `service-control.ps1`，透過服務包裝程式啟動／停止，未提升權限時以 UAC 要求提升；啟動後等待 `/api/health` 回應（最長 180 秒）。顯示文字依 Windows 顯示語言為繁體中文或英文。開始功能表有對應捷徑。

### 5.3 更新檔 `.xrvupd`

ZIP 檔，內含 `manifest.json`（格式、產品、版本、可升級的最低版本、發布日期、版本說明、每個檔案的 SHA-256）、`manifest.sig`（Ed25519 簽章）、`payload/app/…`，以及選用的 `payload/python/…`（未包含時沿用目前版本的執行環境）。

上傳後平台服務依序檢查：簽章 → 產品 → 檔案雜湊 → 版本比目前新 → 目前版本不低於最低版本 → 授權有效；全部通過才展開到 `versions/<版本>/`。

### 5.4 進版與退版

平台服務與啟動器之間以檔案溝通（`updates/requests/*.json`、`updates/status.json`），平台服務不直接操作版本目錄。

- **進版**：停止服務 → 快照（SQLite 線上備份、設定、授權、校正設定檔）→ 切換版本 → 啟動 → 自我檢查（服務回應、版本正確、內建標準影像分析結果與預期一致）→ 成功則保留最近 3 個版本；失敗則還原快照、切回原版本並記錄 `system.update_failed`。
- **退版**：只能退回有「該版本升到目前版本」快照的版本。停止服務 → 匯出快照之後新增的紀錄為退版封存檔 → 還原快照 → 切換版本 → 啟動 → 自我檢查。
- **退版封存檔**：升到相容版本後，於「系統管理 > 軟體更新」匯入，合併回資料庫。同一封存檔只能匯入一次；配方（代碼＋版本）、批號、影像（雜湊值）已存在時沿用既有資料，不重複建立。

### 5.5 原廠端工具

`tools/release/make_update.py` 單獨產生更新檔；一般以 `build_release.py --update-key` 同時產生（第 6 節）。

---

## 6. 發行建置（原廠端）

### 6.1 指令

```
.venv\Scripts\python tools\release\build_release.py --update-key <update 私鑰.pem> [--min-from 0.1.0]
       [--notes-zh "…"] [--notes-en "…"] [--update-with-runtime] [--sign "<簽章指令> $f"]
```

| 步驟 | 內容 |
|---|---|
| 1 | `npm run build` 建置前端（`--skip-web` 略過） |
| 2 | 下載並快取 Python embeddable、服務包裝程式、繁中安裝語系檔（`build/cache/`） |
| 3 | 組出安裝目錄樹 `build/release/<版本>/stage/`；依 `tools/release/runtime-requirements.txt` 以固定版本安裝依賴（OpenCV 使用 headless 版本） |
| 4 | 冒煙測試：以 stage 內的啟動器實際啟動服務（不設 `PYTHONPATH`），確認版本與內建標準影像自我檢查通過（`--no-smoke` 略過） |
| 5 | Inno Setup 編譯 `installer/xrayvision.iss` → `X-RayVision-<版本>-setup.exe` |
| 6 | 指定 `--update-key` 時產生 `X-RayVision-<版本>.xrvupd` |
| 7 | `build-info.json`：外部元件與產出檔的 SHA-256 |

建置需要：專案虛擬環境、Node.js、Inno Setup 6（`ISCC.exe`，可用環境變數 `ISCC` 指定）、可連網下載外部元件（首次）。

### 6.2 安裝程式行為

- 需要系統管理員權限；Windows 10 1809 以上 64 位元。
- 已安裝時拒絕再次安裝，提示改由網頁進版；重新安裝需先解除安裝。
- 安裝後寫入 `launcher.json`（已存在則保留）、註冊並啟動服務，最多等待 180 秒自我檢查通過；逾時提示記錄檔位置，不中止安裝。
- 開始功能表與（選用）桌面捷徑開啟 `http://127.0.0.1:8600/`。
- 解除安裝：停止並移除服務，刪除安裝目錄（含進版後新增的版本）；**保留資料目錄**並提示位置。
- 安裝介面語言：繁體中文（Inno Setup 非官方語系檔）與英文，依 Windows 顯示語言自動選擇。

### 6.3 程式碼簽章

設備電腦已安裝防毒軟體，正式發行的安裝程式應以程式碼簽章憑證簽署。`--sign` 由 Inno Setup 簽署 setup.exe 與解除安裝程式；服務包裝程式（第三方未簽章執行檔）需在建置前以同一憑證另行簽署；Python 執行檔已由 Python 軟體基金會簽署。

```
build_release.py --sign "signtool sign /fd sha256 /tr http://timestamp.digicert.com /td sha256 /f <憑證.pfx> /p <密碼> $f"
```

目前尚未取得憑證，產出為未簽章版本。

### 6.4 正式發行前必須更換的金鑰

`xrayvision/keys/` 內的三把公鑰（授權、更新、問題回報包）與 `tools/keys/` 內的私鑰都是**開發用金鑰**。正式發行前：

1. 以 `license_admin.py keygen` 產生授權簽章金鑰對；更新簽章同為 Ed25519，可用同一指令另產生一組；問題回報包加密為 RSA 金鑰對（以 cryptography 或 OpenSSL 產生）。
2. 公鑰替換 `xrayvision/keys/*.pem`；私鑰離線保存（不放在建置電腦與版控），建議兩份備份。
3. 以開發金鑰簽發的授權檔與更新檔在正式版全部無效。

---

## 7. 驗證狀態

| 項目 | 狀態 |
|---|---|
| 帳號、權限、鎖定、首次設定、變更密碼 | 自動測試（`tests/test_auth.py`） |
| 授權各狀態、機器碼容許、模組授權、停用 | 自動測試（`tests/test_license.py`） |
| 進版成功、進版失敗自動退回、退版與封存檔匯入 | 端到端測試（`tests/test_update_e2e.py`，實際啟動啟動器與服務，約 3 分鐘，標記 slow） |
| 發行目錄樹以 embeddable Python 啟動並通過自我檢查 | 建置時冒煙測試（2026-09-23 通過） |
| setup.exe 編譯、服務包裝設定解析 | 已在開發電腦確認 |
| **setup.exe 實際安裝、服務註冊與開機啟動、解除安裝** | **尚未執行**（需系統管理員權限，建議在乾淨的 Windows 10 虛擬機驗證） |
| **服務身分下以 CTRL_BREAK 正常停止平台服務** | **尚未驗證**；若無效會在 30 秒後結束行程樹（資料庫具交易保護，佇列會在重新啟動時復原） |
| 設備電腦實機（防毒軟體、原廠軟體並行、5120×2160 螢幕） | 尚未執行，待現場 |

---

## 8. 第 5 階段對部署的影響

| 項目 | 內容 |
|---|---|
| 執行環境 | 加入 ONNX Runtime（DirectML 版）與相依套件，約增加 25 MB；0.1.0 之後的更新檔必須包含執行環境（`build_release.py --update-with-runtime`） |
| 資料庫 | 結構版本 3（模組驗證狀態）、4（深度學習模型）、5（標註）；升版時自動遷移，快照可還原 |
| 資料目錄 | 新增 `models/`（匯入的模型檔）；模型檔只新增，不需快照 |
| GPU | 預設關閉；DirectML 需 Windows 10 1903 以上與支援 DirectX 12 的顯示卡 |
