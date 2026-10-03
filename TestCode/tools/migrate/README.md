# 搬成獨立庫

TestCode 原本是 `Python` 庫底下的一個資料夾。2026-10 起改為獨立的 Git 庫，從頭開始，不帶舊歷史；舊歷史留在原 `Python` 庫。

## 步驟

1. **在 GitHub 建立空的新庫**：不要勾選 README、.gitignore、License。
2. **在原 Python 庫的 `TestCode/` 執行搬庫腳本**：
   ```powershell
   powershell -ExecutionPolicy Bypass -File tools\migrate\new-repo.ps1 -Target "D:\Working Space\<新庫名>" -RepoName <新庫名> -IncludeLocal -Push
   ```
   - `-IncludeLocal` 會一併複製只留本機的資料：各專案 `docs/` 與 `TEMP/3d-app-plan.md`。它們在新庫一樣不進版控。
   - 帳號不是 `p0l8u1t7o` 時加 `-Owner <帳號>`；remote 網址不同時加 `-Remote <url>`。
   - 不加 `-Push` 時，先檢查新資料夾的內容，再自己 `git push -u origin main`。
3. **設定 Pages**：GitHub → Settings → Pages → Source 選 **GitHub Actions**。之後每次推送到 `main`，`.github/workflows/pages.yml` 都會先跑快速檢查，通過才發布；PR 只檢查、不發布。
4. **建立新電腦（或新資料夾）的環境**：
   ```powershell
   powershell -ExecutionPolicy Bypass -File setup.ps1 -All
   ```
   需求說明見根目錄的 `REQUIREMENTS.md`。
5. **確認新庫正常後，再處理原 Python 庫**：網站能開、本機 `node core/tools/check.mjs` 全過之後，自行決定要不要移除原庫的 `TestCode/` 與根目錄 `.github/workflows/static.yml`。舊的 Pages 網址（`/Python/`）在移除前會繼續存在。

## 搬庫後和之前不同的地方

| 項目 | 之前（Python 庫） | 之後（獨立庫） |
|---|---|---|
| 指令路徑 | `node TestCode/core/tools/…` | `node core/tools/…`（庫根目錄） |
| Pages 工作流程 | 外層 `.github/workflows/static.yml` | 根目錄 `.github/workflows/pages.yml`（加上 PR 檢查） |
| Pages 網址 | `https://p0l8u1t7o.github.io/Python/` | `https://<帳號>.github.io/<新庫名>/` |
| ffmpeg | 進版控（`MilitaryGradePC/tools/bin/`） | 不進版控，`setup.ps1 -Ffmpeg` 下載 |
| `.venv`、`*.pyc` | 外層 `.gitignore` 擋掉 | 根目錄 `.gitignore` |
| Claude Code 記憶 | 使用者層級記憶（綁舊路徑） | 根目錄 `CLAUDE.md`（隨庫走） |

網站內的連結都是相對路徑，庫名改變不影響網站；只有 README 裡寫死的 Pages 網址由搬庫腳本代換。
