<#
.SYNOPSIS
    Build the VisionSequence release: a self-contained tree (embedded Python + all packages), a zip and the setup wizard.

.DESCRIPTION
    Vendor side, on a PC with internet (first time) - later builds can run with -Offline from build\cache.
    Steps: checks -> frontend build -> cached downloads (python embeddable, get-pip, NSSM, Caddy, VC++ runtime)
    -> wheelhouse (pip download, win_amd64/cp312) -> assemble build\release\VisionSequence-<ver>\ -> self-check
    (imports, manage.py check/migrate/doctor in a temp VS_HOME, tests.test_release) -> zip + SHA256SUMS.txt
    -> VisionSequence-Setup-<ver>.exe when Inno Setup 6 (ISCC.exe) is installed.

.EXAMPLE
    .\scripts\build_release.ps1                 # everything
    .\scripts\build_release.ps1 -Offline        # no downloads, use build\cache
    .\scripts\build_release.ps1 -SkipFrontend -SkipInstaller -SkipTests   # quick tree for a local trial
#>
[CmdletBinding()]
param(
    [string]$Version = '',
    [string]$OutDir = '',
    [string]$PythonVersion = '3.12.10',
    [string]$NssmUrl = 'https://nssm.cc/ci/nssm-2.24-101-g897c7ad.zip',
    [string]$CaddyVersion = '2.9.1',
    [string]$Iscc = '',
    [switch]$Offline,
    [switch]$SkipChecks,
    [switch]$SkipFrontend,
    [switch]$SkipInstaller,
    [switch]$SkipTests,
    [switch]$KeepTree
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
. (Join-Path $PSScriptRoot 'vslib.ps1')
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')
Set-Location $root
if (-not $Version) {
    $m = [regex]::Match((Get-Content -LiteralPath (Join-Path $root 'apps\vision\__init__.py') -Raw), '__version__\s*=\s*"([^"]+)"')
    if (-not $m.Success) { throw "Cannot read __version__ from apps\vision\__init__.py" }
    $Version = $m.Groups[1].Value
}
if (-not $OutDir) { $OutDir = Join-Path $root 'build\release' }
$cache = Join-Path $root 'build\cache'
$pyTag = ($PythonVersion -split '\.')[0..1] -join ''          # 312
$wheelhouse = Join-Path $cache "wheels-cp$pyTag"
$treeName = "VisionSequence-$Version"
$tree = Join-Path $OutDir $treeName
$zipPath = Join-Path $OutDir "$treeName-win64.zip"
$devPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $devPython)) { $devPython = 'py' }
$started = Get-Date
New-Item -ItemType Directory -Force -Path $cache, $OutDir, $wheelhouse | Out-Null

function Step([string]$Text) { Write-Host ("`n==> " + $Text) -ForegroundColor Cyan }

function Native([scriptblock]$Cmd, [string]$What) {
    # 原生程式（pip、npm、robocopy）把警告寫到 stderr，Stop 模式會把它當成錯誤中止；這裡放寬並只看離開碼
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Cmd; $code = $LASTEXITCODE } finally { $ErrorActionPreference = $prev }
    if ($code) { throw "$What failed (exit $code)" }
}

function Get-Cached([string]$Url, [string]$Name) {
    # 下載到 build\cache 並記 sha256（第一次信任、之後每次核對）；-Offline 只用快取
    $dest = Join-Path $cache $Name
    $sumFile = "$dest.sha256"
    if (-not (Test-Path -LiteralPath $dest)) {
        if ($Offline) { throw "Offline build but $Name is not in $cache" }
        Write-Host "  downloading $Url"
        Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $dest
    }
    $hash = (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLower()
    if (Test-Path -LiteralPath $sumFile) {
        $expected = (Get-Content -LiteralPath $sumFile -Raw).Trim().ToLower()
        if ($expected -ne $hash) { throw "SHA256 mismatch for $Name (cache says $expected, file is $hash). Delete build\cache\$Name to re-download." }
    } else {
        [IO.File]::WriteAllText($sumFile, $hash + "`n")
        Write-Host "  recorded sha256 $hash  $Name"
    }
    return $dest
}

function Copy-Tree([string]$Src, [string]$Dst, [string[]]$ExcludeDirs = @(), [string[]]$ExcludeFiles = @()) {
    $xd = @('__pycache__', '.pytest_cache', '.ruff_cache') + $ExcludeDirs
    $xf = @('*.pyc', '*.pyo', '.DS_Store', 'Thumbs.db') + $ExcludeFiles
    & robocopy $Src $Dst /E /NFL /NDL /NJH /NJS /NP /R:2 /W:1 /XD @xd /XF @xf | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy $Src -> $Dst failed ($LASTEXITCODE)" }
}

# ---- 0. 檢查 ---------------------------------------------------------------------------------------
Step "Release $Version -> $tree"
if (-not $SkipChecks) {
    if (-not $SkipFrontend) { foreach ($t in @('node', 'npm')) { if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { throw "$t not found (needed for the frontend build; use -SkipFrontend with an existing frontend\dist)." } } }
    if ($devPython -eq 'py' -and -not (Get-Command py -ErrorAction SilentlyContinue)) { throw "No .venv and no py launcher: run scripts\dev.ps1 -Setup first." }
    $status = (& git -C $root status --porcelain -- . 2>$null)
    if ($status) { Write-VsWarn "Working tree has uncommitted changes; release.json records the commit, not these edits." }
}
$commit = ''
try { $commit = (& git -C $root rev-parse --short HEAD 2>$null).Trim() } catch { }

# ---- 1. 前端 -----------------------------------------------------------------------------------------
if ($SkipFrontend) {
    if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend\dist\index.html'))) { throw "frontend\dist\index.html missing and -SkipFrontend given." }
    Step "Frontend: using existing frontend\dist"
} else {
    Step "Frontend build"
    Push-Location (Join-Path $root 'frontend')
    try {
        if (-not (Test-Path 'node_modules')) { Native { & npm ci } 'npm ci' }
        Remove-Item Env:VITE_SOURCEMAP -ErrorAction SilentlyContinue
        Native { & npm run -s build } 'npm run build'
    } finally { Pop-Location }
}

# ---- 2. 下載（快取） ---------------------------------------------------------------------------------
Step "Third-party downloads (build\cache)"
$pyZip = Get-Cached "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" "python-$PythonVersion-embed-amd64.zip"
$getPip = Get-Cached 'https://bootstrap.pypa.io/get-pip.py' 'get-pip.py'
$nssmZip = Get-Cached $NssmUrl ([IO.Path]::GetFileName($NssmUrl))
$caddyZip = Get-Cached "https://github.com/caddyserver/caddy/releases/download/v$CaddyVersion/caddy_${CaddyVersion}_windows_amd64.zip" "caddy_${CaddyVersion}_windows_amd64.zip"
$vcRedist = Get-Cached 'https://aka.ms/vs/17/release/vc_redist.x64.exe' 'vc_redist.x64.exe'

# ---- 3. wheelhouse -----------------------------------------------------------------------------------
Step "Wheelhouse for cp$pyTag win_amd64 ($wheelhouse)"
$pipDl = @('-m', 'pip', 'download', '--disable-pip-version-check', '-r', (Join-Path $root 'requirements.txt'), '-d', $wheelhouse,
           '--platform', 'win_amd64', '--python-version', ($PythonVersion -replace '\.\d+$', ''), '--implementation', 'cp', '--only-binary=:all:')
if ($Offline) { $pipDl += @('--no-index', '--find-links', $wheelhouse) }
Native { & $devPython @pipDl } 'pip download'
# pip 本身也要在 wheelhouse（get-pip.py --no-index 從這裡裝）
$pipSelf = @('-m', 'pip', 'download', '--disable-pip-version-check', 'pip', '-d', $wheelhouse)
if ($Offline) { $pipSelf += @('--no-index', '--find-links', $wheelhouse) }
Native { & $devPython @pipSelf } 'pip download pip'

# ---- 4. 組樹 --------------------------------------------------------------------------------------------
Step "Assembling the tree"
if (Test-Path -LiteralPath $tree) { Remove-Item -LiteralPath $tree -Recurse -Force }
New-Item -ItemType Directory -Force -Path $tree | Out-Null
Add-Type -AssemblyName System.IO.Compression.FileSystem

# 4a. 內嵌 Python：._pth 決定 sys.path（不受客戶 PC 上其他 Python 影響）；.. 是版本樹根（apps、config）
$pyDir = Join-Path $tree 'python'
[IO.Compression.ZipFile]::ExtractToDirectory($pyZip, $pyDir)
$pth = Join-Path $pyDir "python$pyTag._pth"
[IO.File]::WriteAllText($pth, "python$pyTag.zip`r`n.`r`nLib\site-packages`r`n..`r`nimport site`r`n", (New-Object Text.ASCIIEncoding))
New-Item -ItemType Directory -Force -Path (Join-Path $pyDir 'Lib\site-packages') | Out-Null
$py = Join-Path $pyDir 'python.exe'
$env:PYTHONDONTWRITEBYTECODE = ''
Native { & $py $getPip --no-warn-script-location --disable-pip-version-check --no-index --find-links $wheelhouse } 'get-pip'
Native { & $py -m pip install --disable-pip-version-check --no-warn-script-location --no-index --find-links $wheelhouse -r (Join-Path $root 'requirements.txt') } 'pip install into the embedded Python'
Get-ChildItem -LiteralPath $pyDir -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force

# 4b. 平台程式碼
Copy-Tree (Join-Path $root 'apps') (Join-Path $tree 'apps')
Copy-Tree (Join-Path $root 'config') (Join-Path $tree 'config')
Copy-Tree (Join-Path $root 'vscapture') (Join-Path $tree 'vscapture') @('ui', 'cameras')   # 伺服端只用 protocol.py
foreach ($f in @('manage.py', 'requirements.txt', 'requirements-dl.txt', 'requirements-dev.txt', '.env.example', 'README.md')) {
    if (Test-Path -LiteralPath (Join-Path $root $f)) { Copy-Item -LiteralPath (Join-Path $root $f) -Destination $tree }
}
Copy-Tree (Join-Path $root 'frontend\dist') (Join-Path $tree 'frontend\dist') @() @('*.map')
Copy-Tree (Join-Path $root 'docs') (Join-Path $tree 'docs')
New-Item -ItemType Directory -Force -Path (Join-Path $tree 'scripts') | Out-Null
foreach ($f in @('vslib.ps1', 'service.ps1', 'proxy.ps1', 'vsctl.ps1', 'vsctl.cmd', 'install.ps1', 'install_service.ps1')) {
    Copy-Item -LiteralPath (Join-Path $root "scripts\$f") -Destination (Join-Path $tree 'scripts')
}
# 範例外掛：放 examples\，不放樹內的 plugins\（那會變成第二個 plugins 套件）
New-Item -ItemType Directory -Force -Path (Join-Path $tree 'examples\plugins') | Out-Null
Get-ChildItem -LiteralPath (Join-Path $root 'plugins') -File -Filter 'example_*' | Copy-Item -Destination (Join-Path $tree 'examples\plugins')

# 4c. 工具
$tools = Join-Path $tree 'tools'
New-Item -ItemType Directory -Force -Path $tools, (Join-Path $tools 'LICENSES') | Out-Null
$nssmTmp = Join-Path $cache 'nssm-unpacked'
if (Test-Path -LiteralPath $nssmTmp) { Remove-Item -LiteralPath $nssmTmp -Recurse -Force }
[IO.Compression.ZipFile]::ExtractToDirectory($nssmZip, $nssmTmp)
$nssmExe = Get-ChildItem -LiteralPath $nssmTmp -Recurse -Filter 'nssm.exe' | Where-Object { $_.FullName -match 'win64' } | Select-Object -First 1
if (-not $nssmExe) { throw "nssm.exe (win64) not found in $nssmZip" }
Copy-Item -LiteralPath $nssmExe.FullName -Destination $tools
Get-ChildItem -LiteralPath $nssmTmp -Recurse -Filter 'README.txt' | Select-Object -First 1 | Copy-Item -Destination (Join-Path $tools 'LICENSES\nssm-README.txt')
$caddyTmp = Join-Path $cache 'caddy-unpacked'
if (Test-Path -LiteralPath $caddyTmp) { Remove-Item -LiteralPath $caddyTmp -Recurse -Force }
[IO.Compression.ZipFile]::ExtractToDirectory($caddyZip, $caddyTmp)
Copy-Item -LiteralPath (Join-Path $caddyTmp 'caddy.exe') -Destination $tools
if (Test-Path -LiteralPath (Join-Path $caddyTmp 'LICENSE')) { Copy-Item -LiteralPath (Join-Path $caddyTmp 'LICENSE') -Destination (Join-Path $tools 'LICENSES\caddy-LICENSE.txt') }
Copy-Item -LiteralPath $vcRedist -Destination $tools
[IO.File]::WriteAllText((Join-Path $tools 'LICENSES\README.txt'), "nssm.exe: NSSM (public domain, https://nssm.cc)`r`ncaddy.exe: Caddy $CaddyVersion (Apache-2.0, https://caddyserver.com)`r`nvc_redist.x64.exe: Microsoft Visual C++ Redistributable (Microsoft license)`r`npython\: CPython $PythonVersion (PSF license) and the packages listed in requirements.txt`r`n")

# 4d. 擷取端安裝檔（data\downloads 有就帶）
$dl = Join-Path $root 'data\downloads'
if (Test-Path -LiteralPath (Join-Path $dl 'manifest.json')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $tree 'capture-client') | Out-Null
    Copy-Item -LiteralPath (Join-Path $dl 'manifest.json') -Destination (Join-Path $tree 'capture-client')
    $man = Get-Content -LiteralPath (Join-Path $dl 'manifest.json') -Raw | ConvertFrom-Json
    if ($man.filename -and (Test-Path -LiteralPath (Join-Path $dl $man.filename))) { Copy-Item -LiteralPath (Join-Path $dl $man.filename) -Destination (Join-Path $tree 'capture-client') }
    Write-VsOk "Capture client $($man.version) included"
} else {
    # 沒有 manifest 但有 zip（package_capture_client.py 之前的產物）：從檔名補一份，客戶端頁才有得下載
    $zipFile = Get-ChildItem -LiteralPath $dl -Filter 'VisionSequenceCapture-*-win64.zip' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($zipFile) {
        New-Item -ItemType Directory -Force -Path (Join-Path $tree 'capture-client') | Out-Null
        Copy-Item -LiteralPath $zipFile.FullName -Destination (Join-Path $tree 'capture-client')
        $ver = ($zipFile.Name -replace '^VisionSequenceCapture-', '' -replace '-win64\.zip$', '')
        $man = @{ version = $ver; filename = $zipFile.Name; size = $zipFile.Length; sha256 = (Get-FileHash -LiteralPath $zipFile.FullName -Algorithm SHA256).Hash.ToLower(); built_at = $zipFile.LastWriteTime.ToString('s') } | ConvertTo-Json
        [IO.File]::WriteAllText((Join-Path $tree 'capture-client\manifest.json'), $man + "`n", (New-Object Text.UTF8Encoding $false))
        Write-VsOk "Capture client $ver included (manifest generated from the zip)"
    } else {
        Write-VsWarn "No data\downloads\manifest.json: the release has no capture client (run scripts\build_capture_client.ps1 first)."
    }
}

# 4e. 版本檔
$built = (Get-Date).ToString('s')
[IO.File]::WriteAllText((Join-Path $tree 'VERSION'), $Version + "`n")
$fileCount = (Get-ChildItem -LiteralPath $tree -Recurse -File).Count
$release = @{ product = 'VisionSequence'; version = $Version; built_at = $built; commit = $commit; python = $PythonVersion; caddy = $CaddyVersion; files = $fileCount; layout = 'app/<version> + current junction; VS_HOME two levels up' } | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $tree 'release.json'), $release + "`n", (New-Object Text.UTF8Encoding $false))
$readme = (Get-Content -LiteralPath (Join-Path $root 'scripts\release_readme.txt') -Raw).Replace('{{VERSION}}', $Version).Replace('{{BUILT}}', $built.Substring(0, 10))
[IO.File]::WriteAllText((Join-Path $tree 'README.txt'), $readme, (New-Object Text.UTF8Encoding $false))
Write-VsOk "$fileCount files, $([math]::Round((Get-ChildItem -LiteralPath $tree -Recurse -File | Measure-Object Length -Sum).Sum / 1MB)) MB"

# ---- 5. 自檢 ---------------------------------------------------------------------------------------------
Step "Self-check with the embedded Python"
$env:VS_HOME = Join-Path $cache 'selfcheck-home'
if (Test-Path -LiteralPath $env:VS_HOME) { Remove-Item -LiteralPath $env:VS_HOME -Recurse -Force }
New-Item -ItemType Directory -Force -Path $env:VS_HOME | Out-Null
[IO.File]::WriteAllText((Join-Path $env:VS_HOME '.env'), "DEBUG=0`nSECRET_KEY=selfcheck-$(New-VsSecret 8)`nALLOWED_HOSTS=localhost`nVISION_API_KEY=x`nVISION_TCP_AUTH=x`n")
$env:PYTHONIOENCODING = 'utf-8'
$env:LOG_LEVEL = 'WARNING'
$env:DJANGO_SETTINGS_MODULE = 'config.settings'
$env:PYTHONDONTWRITEBYTECODE = '1'   # 自檢不留 __pycache__ 在樹裡
Push-Location $tree
try {
    Native { & $py -c "import cv2, numpy, scipy, django, ninja, onnxruntime, uvicorn, pymodbus, PIL, whitenoise, orjson, lz4, dotenv; import sys; print('imports ok', sys.version.split()[0], 'cv2', cv2.__version__, 'django', django.__version__)" } 'import self-check'
    Native { & $py -c "import sys; assert not any('.venv' in p for p in sys.path), sys.path; print('sys.path ok:', [p for p in sys.path if p][:4])" } 'sys.path check'
    Native { & $py manage.py check } 'manage.py check'
    Native { & $py manage.py migrate --noinput | Select-Object -Last 1 } 'migrate'
    $prevEap = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    & $py manage.py doctor | Select-Object -Last 3
    $ErrorActionPreference = $prevEap
} finally {
    Pop-Location
    Remove-Item Env:VS_HOME -ErrorAction SilentlyContinue
    Remove-Item Env:LOG_LEVEL -ErrorAction SilentlyContinue
    Remove-Item Env:DJANGO_SETTINGS_MODULE -ErrorAction SilentlyContinue
}
if (-not $SkipTests) {
    Step "tests.test_release against the tree"
    $env:VS_RELEASE_DIR = $tree
    try {
        Native { & $devPython manage.py test tests.test_release --noinput } 'tests.test_release'
    } finally { Remove-Item Env:VS_RELEASE_DIR -ErrorAction SilentlyContinue }
}

# ---- 6. zip + 安裝程式 --------------------------------------------------------------------------------------
Step "Zip"
if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
[IO.Compression.ZipFile]::CreateFromDirectory($tree, $zipPath, [IO.Compression.CompressionLevel]::Optimal, $true)
Write-VsOk "$zipPath ($([math]::Round((Get-Item -LiteralPath $zipPath).Length / 1MB)) MB)"
$artifacts = @($zipPath)
if (-not $SkipInstaller) {
    if (-not $Iscc) {
        foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) { if (Test-Path -LiteralPath $c) { $Iscc = $c; break } }
        if (-not $Iscc) { $cmd = Get-Command ISCC.exe -ErrorAction SilentlyContinue; if ($cmd) { $Iscc = $cmd.Source } }
    }
    if ($Iscc) {
        Step "Setup wizard (Inno Setup)"
        Native { & $Iscc "/DAppVersion=$Version" "/DSourceDir=$tree" "/DOutDir=$OutDir" /Q (Join-Path $root 'scripts\installer.iss') } 'ISCC'
        $setup = Join-Path $OutDir "VisionSequence-Setup-$Version.exe"
        Write-VsOk "$setup ($([math]::Round((Get-Item -LiteralPath $setup).Length / 1MB)) MB)"
        $artifacts += $setup
    } else {
        Write-VsWarn "Inno Setup 6 (ISCC.exe) not found: no setup wizard, the zip is complete on its own. Install Inno Setup or pass -Iscc <path>."
    }
}
$sums = $artifacts | ForEach-Object { "{0}  {1}" -f (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLower(), (Split-Path -Leaf $_) }
[IO.File]::WriteAllText((Join-Path $OutDir 'SHA256SUMS.txt'), (($sums -join "`n") + "`n"))
if (-not $KeepTree) { Write-Host "  (tree kept at $tree; delete it or pass -KeepTree to be explicit)" -ForegroundColor DarkGray }
Write-Host ""
Write-Host "Release $Version built in $([int]((Get-Date) - $started).TotalMinutes) min:" -ForegroundColor Green
$sums | ForEach-Object { Write-Host "  $_" }
Write-Host "  DL add-on packs: scripts\build_dl_pack.ps1 -Cuda cu128 | -Cpu"
