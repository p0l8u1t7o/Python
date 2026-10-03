<#
  把 TestCode 搬成獨立的新 Git 庫（從頭開始，不帶舊歷史）。
    powershell -ExecutionPolicy Bypass -File tools\migrate\new-repo.ps1 -Target D:\Work\<新庫名> -RepoName <新庫名> [-Owner p0l8u1t7o] [-IncludeLocal] [-Push]
  做的事：
    1. 複製目前 TestCode 中「已追蹤＋未被忽略」的檔案（不含 ffmpeg 執行檔；TEMP、docs、.venv 等本機產物本來就被忽略）
    2. -IncludeLocal：另外複製只留本機的資料（各專案 docs/、TEMP/3d-app-plan.md），新庫中它們仍被 .gitignore 排除
    3. 把 Markdown 裡舊的 Pages 網址 https://p0l8u1t7o.github.io/Python/ 換成 https://<Owner>.github.io/<RepoName>/
    4. git init -b main、建立初始 commit、設定 origin（https://github.com/<Owner>/<RepoName>.git 或 -Remote）
    5. -Push：推送到 origin（GitHub 上要先建立空的新庫）
  搬完的後續步驟見 tools/migrate/README.md。
#>
param(
  [Parameter(Mandatory = $true)][string]$Target,
  [Parameter(Mandatory = $true)][string]$RepoName,
  [string]$Owner = 'p0l8u1t7o',
  [string]$Remote = '',
  [switch]$IncludeLocal,
  [switch]$Push
)
$ErrorActionPreference = 'Stop'
$Root = (Resolve-Path (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) '..\..')).Path
$OldPages = 'https://p0l8u1t7o.github.io/Python/'
$NewPages = "https://$($Owner.ToLower()).github.io/$RepoName/"
if (-not $Remote) { $Remote = "https://github.com/$Owner/$RepoName.git" }

if (Test-Path $Target) {
  if (Get-ChildItem -Force $Target | Select-Object -First 1) { throw "目標資料夾已存在且不是空的：$Target" }
} else { New-Item -ItemType Directory $Target | Out-Null }
$Target = (Resolve-Path $Target).Path
Write-Host "來源：$Root"
Write-Host "目標：$Target"

# ---------------------------------------------------------------- 1. 已追蹤＋未被忽略的檔案
Push-Location $Root
try {
  $raw = & git -c core.quotepath=off ls-files --cached --others --exclude-standard -z -- .
  if ($LASTEXITCODE -ne 0) { throw 'git ls-files 失敗（請在原本的 Python 庫裡執行）' }
} finally { Pop-Location }
$files = ($raw -join '') -split "`0" | Where-Object { $_ } | Sort-Object -Unique
$skip = '^MilitaryGradePC/tools/bin/'
$copied = 0
foreach ($rel in $files) {
  if ($rel -match $skip) { continue }
  $src = Join-Path $Root $rel
  if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { continue }   # 已刪除但仍在索引中的檔案
  $dst = Join-Path $Target $rel
  New-Item -ItemType Directory -Force (Split-Path -Parent $dst) | Out-Null
  Copy-Item -LiteralPath $src -Destination $dst -Force
  $copied++
}
Write-Host "複製 $copied 個檔案"

# ---------------------------------------------------------------- 2. 本機資料（選用）
if ($IncludeLocal) {
  $local = 0
  Get-ChildItem -Directory $Root | ForEach-Object {
    $docs = Join-Path $_.FullName 'docs'
    if ((Test-Path $docs) -and (Test-Path (Join-Path $_.FullName 'web\index.html'))) {
      Copy-Item -Recurse -Force $docs (Join-Path $Target $_.Name); $local++
    }
  }
  $plan = Join-Path $Root 'TEMP\3d-app-plan.md'
  if (Test-Path $plan) { New-Item -ItemType Directory -Force (Join-Path $Target 'TEMP') | Out-Null; Copy-Item $plan (Join-Path $Target 'TEMP') -Force; $local++ }
  Write-Host "本機資料：$local 項（docs/ 與 TEMP 在新庫仍不進版控）"
}

# ---------------------------------------------------------------- 3. Pages 網址
$changed = 0
Get-ChildItem -Recurse -File -Path $Target -Include *.md | Where-Object { $_.FullName.Substring($Target.Length) -notmatch '(^|\\)(docs|TEMP|\.git|migrate)\\' } | ForEach-Object {   # tools/migrate 的說明要保留舊網址做對照
  $text = [IO.File]::ReadAllText($_.FullName, [Text.Encoding]::UTF8)
  if ($text.Contains($OldPages)) {
    [IO.File]::WriteAllText($_.FullName, $text.Replace($OldPages, $NewPages), (New-Object Text.UTF8Encoding($false))); $changed++
  }
}
Write-Host "Pages 網址：$OldPages → $NewPages（$changed 個檔案）"

# ---------------------------------------------------------------- 4. 新庫
Push-Location $Target
try {
  & git init -b main | Out-Null
  & git -c core.safecrlf=false add -A
  & git -c core.safecrlf=false commit -q -m "Import the 3D automation demos as a standalone repository" -m "Copied from the TestCode folder of the Python repository without its history. ffmpeg binaries are downloaded by setup.ps1 -Ffmpeg; project docs/ stay local."
  if ($LASTEXITCODE -ne 0) { throw 'git commit 失敗（請確認 git 已設定 user.name 與 user.email）' }
  & git remote add origin $Remote
  Write-Host "初始 commit：$((& git log --oneline -1).Trim())"
  Write-Host "origin：$Remote"
  if ($Push) {
    & git push -u origin main
    if ($LASTEXITCODE -ne 0) { throw '推送失敗：請確認 GitHub 上已建立空的新庫，且有推送權限' }
  }
} finally { Pop-Location }

Write-Host ''
Write-Host '接下來：' -ForegroundColor Cyan
if (-not $Push) { Write-Host "  1. 在 GitHub 建立空的新庫 $Owner/$RepoName，然後：cd `"$Target`"; git push -u origin main" }
Write-Host '  2. GitHub → Settings → Pages → Source 選 GitHub Actions（推送後 Actions 會跑檢查並發布）'
Write-Host "  3. cd `"$Target`"; powershell -ExecutionPolicy Bypass -File setup.ps1 -All"
Write-Host "  4. 網站：$NewPages"
Write-Host '  5. 確認新庫正常後，再決定要不要從原 Python 庫移除 TestCode 與根目錄的 .github/workflows/static.yml'
