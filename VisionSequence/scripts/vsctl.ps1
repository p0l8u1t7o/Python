<#
.SYNOPSIS
    vsctl - the VisionSequence station command line (Windows PowerShell 5.1).

.DESCRIPTION
    Run from the install root as "vsctl <command>" (vsctl.cmd forwards here) or from a checkout as scripts\vsctl.ps1.

    Service        start | stop | restart | status | run (foreground, for debugging) | logs [-Tail N] [-Follow] [-Proxy]
    Operations     doctor [-Json] | backup [-Out x.zip] [--with-images] | restore <zip> | purge [--dry-run] | manage <manage.py args>
    Versions       update <release.zip> [-Keep N] | rollback [<version>] [-RestoreDb] | versions [prune] [-Keep N] | version
    Plugins        plugins list | install <zip|folder> [-Online] | deps [<name>] [-Online] | rescan
    Deep learning  dl check [-Predict] | dl install <pack.zip> [-Predict]
    Configuration  env list | get KEY | set KEY=VALUE | admin create <user> [-PasswordEnv NAME]
    Network        service install|uninstall [-Mode service|task] [-User -Password] [-Interactive]
                   proxy configure|install|uninstall|start|stop|restart|status|export-root|trust [-Https internal|custom|none] [-HostNames a,b] [-Port 443] [-Cert -Key]
                   firewall [-Subnet 192.168.1.0/24] [-Ports 5020,5021] [-Remove] | certs export|import
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][string]$Command = 'help',
    [Parameter(Position = 1)][string]$Sub = '',
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Rest = @(),
    [int]$Tail = 50,
    [switch]$Follow,
    [switch]$Proxy,
    [switch]$Online,
    [int]$Keep = 2,
    [switch]$RestoreDb,
    [switch]$Predict,
    [switch]$Force,
    [switch]$Yes,
    [switch]$Json,
    [string]$Subnet = '',
    [string]$Ports = '',
    [switch]$Remove,
    [string]$Https = '',
    [string[]]$HostNames = @(),
    [int]$Port = 0,
    [string]$Cert = '',
    [string]$Key = '',
    [string]$Out = '',
    [string]$File = '',
    [string]$Mode = 'service',
    [string]$User = 'LocalSystem',
    [string]$Password = '',
    [switch]$Interactive,
    [string]$PasswordEnv = '',
    [switch]$DryRun
)

$ErrorActionPreference = 'Stop'
$script:boundKeys = @($PSBoundParameters.Keys)
. (Join-Path $PSScriptRoot 'vslib.ps1')
$layout = Get-VsLayout
$scriptsDir = Join-Path $layout.Current 'scripts'
if (-not (Test-Path -LiteralPath (Join-Path $scriptsDir 'service.ps1'))) { $scriptsDir = $PSScriptRoot }
$serviceScript = Join-Path $scriptsDir 'service.ps1'
$proxyScript = Join-Path $scriptsDir 'proxy.ps1'
$updatesLog = Join-Path $layout.Home 'updates.log'
$appDir = Join-Path $layout.Home 'app'
$packsDir = Join-Path $layout.Home 'packs'
$Rest = @($Rest | Where-Object { $_ -ne $null })

function Show-Help {
    $text = (Get-Content -LiteralPath $PSCommandPath -Raw)
    $m = [regex]::Match($text, '(?s)\.DESCRIPTION\s*(.*?)\s*#>')
    Write-Host "vsctl - VisionSequence $($layout.Version)   home: $($layout.Home)"
    if ($m.Success) { Write-Host $m.Groups[1].Value }
}

function Fail([string]$Message, [int]$Code = 1) { Write-VsFail $Message; exit $Code }

function Require-Python {
    if (-not $layout.Python) { Fail "No Python under $($layout.Current): python\python.exe (release) or .venv\Scripts\python.exe (checkout)." }
}

function Service-Installed { return [bool](Get-Service -Name 'VisionSequence' -ErrorAction SilentlyContinue) -or [bool](Get-ScheduledTask -TaskName 'VisionSequence' -ErrorAction SilentlyContinue) }

function Service-Running {
    $s = Get-Service -Name 'VisionSequence' -ErrorAction SilentlyContinue
    if ($s) { return ($s.Status -eq 'Running') }
    $t = Get-ScheduledTask -TaskName 'VisionSequence' -ErrorAction SilentlyContinue
    if ($t) { return ($t.State -eq 'Running') }
    return $false
}

function Invoke-Service([string]$Action, [hashtable]$Extra = @{}) {
    $splat = @{}
    foreach ($k in @('Mode', 'User', 'Password', 'Interactive', 'Port', 'DryRun')) { if ($script:boundKeys -contains $k) { $splat[$k] = (Get-Variable $k).Value } }
    foreach ($k in $Extra.Keys) { $splat[$k] = $Extra[$k] }
    & $serviceScript $Action @splat
    return $LASTEXITCODE
}

function Invoke-Proxy([string]$Action) {
    $splat = @{}
    foreach ($k in @('Https', 'HostNames', 'Port', 'Cert', 'Key', 'Out', 'File', 'DryRun')) {
        if (($script:boundKeys -contains $k)) { $splat[$k] = (Get-Variable $k).Value }
    }
    & $proxyScript $Action @splat
    return $LASTEXITCODE
}

function Wait-Healthy([int]$HttpPort, [string]$ExpectVersion = '', [int]$Seconds = 60) {
    for ($i = 0; $i -lt $Seconds; $i++) {
        $h = Get-VsHealth $HttpPort
        if ($h) {
            if ($ExpectVersion -and $h.version -ne $ExpectVersion) { Write-VsWarn "healthz reports $($h.version), expected $ExpectVersion" }
            return $true
        }
        Start-Sleep -Seconds 1
    }
    return $false
}

function Migration-Count([string]$Python, [string]$Tree) {
    # 已套用的 migration 數（回滾時判斷資料庫有沒有往前走）
    $env:VS_HOME = $layout.Home
    Push-Location $Tree
    try { $lines = & $Python manage.py showmigrations --plan 2>$null } finally { Pop-Location }
    return @($lines | Where-Object { $_ -match '^\s*\[X\]' }).Count
}

function Append-UpdateLog([string]$Line) {
    Add-Content -LiteralPath $updatesLog -Value ("{0}  {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Line) -Encoding UTF8
}

function Previous-Version {
    if (-not (Test-Path -LiteralPath $updatesLog)) { return '' }
    $last = Get-Content -LiteralPath $updatesLog | Where-Object { $_ -match '\s(update|rollback)\s+(\S+) -> (\S+)' } | Select-Object -Last 1
    if ($last -and $last -match '\s(update|rollback)\s+(\S+) -> (\S+)') { return $Matches[2] }
    return ''
}

function Installed-Versions {
    if (-not (Test-Path -LiteralPath $appDir)) { return @() }
    return @(Get-ChildItem -LiteralPath $appDir -Directory | Where-Object { $_.Name -notmatch '\.(partial|failed|old)' } | Sort-Object { try { [version]$_.Name } catch { [version]'0.0.0' } }, Name)
}

function Current-Target {
    $item = Get-Item -LiteralPath (Join-Path $layout.Home 'current') -ErrorAction SilentlyContinue
    if ($item -and $item.Target) { return ([string]$item.Target).TrimEnd('\') }
    return ''
}

function Set-Current([string]$Target) {
    $link = Join-Path $layout.Home 'current'
    if (Test-Path -LiteralPath $link) { [IO.Directory]::Delete($link) }   # junction：只刪連結不刪目標
    New-Item -ItemType Junction -Path $link -Target $Target | Out-Null
}

function Plugin-Requirements([string]$Dir) {
    # 回傳 @{Name; File; Wheels}：<name>\requirements.txt 或 <name>.requirements.txt
    $items = @()
    if (-not (Test-Path -LiteralPath $Dir)) { return $items }
    foreach ($d in Get-ChildItem -LiteralPath $Dir -Directory | Where-Object { -not $_.Name.StartsWith('_') -and -not $_.Name.StartsWith('.') }) {
        $req = Join-Path $d.FullName 'requirements.txt'
        if (Test-Path -LiteralPath $req) { $items += @{ Name = $d.Name; File = $req; Wheels = (Join-Path $d.FullName 'wheels') } }
    }
    foreach ($f in Get-ChildItem -LiteralPath $Dir -File -Filter '*.requirements.txt') {
        $items += @{ Name = ($f.Name -replace '\.requirements\.txt$', ''); File = $f.FullName; Wheels = (Join-Path $Dir ($f.Name -replace '\.requirements\.txt$', '.wheels')) }
    }
    return $items
}

function Install-PluginDeps([string]$Python, [string]$Only = '', [switch]$AllowOnline) {
    # 先離線（外掛自帶 wheels\ 與站點共用 plugins\_wheels\），-Online 才連 PyPI。回傳失敗的外掛名。
    $failed = @()
    $shared = Join-Path $layout.PluginDir '_wheels'
    foreach ($item in Plugin-Requirements $layout.PluginDir) {
        if ($Only -and $item.Name -ne $Only) { continue }
        Write-VsStep "Plugin dependencies: $($item.Name)"
        $links = @()
        foreach ($w in @($item.Wheels, $shared)) { if (Test-Path -LiteralPath $w) { $links += @('--find-links', $w) } }
        & $Python -m pip install --disable-pip-version-check --no-index @links -r $item.File
        if ($LASTEXITCODE -eq 0) { Write-VsOk "$($item.Name): installed offline"; continue }
        if ($AllowOnline) {
            & $Python -m pip install --disable-pip-version-check @links -r $item.File
            if ($LASTEXITCODE -eq 0) { Write-VsOk "$($item.Name): installed from PyPI"; continue }
        }
        Write-VsWarn "$($item.Name): dependencies not installed. Put cp312/win_amd64 wheels in $($item.Wheels) or $shared (pip download ... --platform win_amd64 --python-version 3.12 --only-binary=:all:), or rerun with -Online."
        $failed += $item.Name
    }
    return $failed
}

function Install-Plugin([string]$Source) {
    if (-not (Test-Path -LiteralPath $Source)) { Fail "Not found: $Source" }
    New-Item -ItemType Directory -Force -Path $layout.PluginDir | Out-Null
    $src = Get-Item -LiteralPath $Source
    $names = @()
    if ($src.PSIsContainer) {
        $dst = Join-Path $layout.PluginDir $src.Name
        if ((Test-Path -LiteralPath $dst) -and -not $Force) { Fail "$dst already exists (use -Force to replace)." }
        if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Recurse -Force }
        Copy-Item -LiteralPath $src.FullName -Destination $dst -Recurse
        $names += $src.Name
    } elseif ($src.Extension -eq '.py') {
        Copy-Item -LiteralPath $src.FullName -Destination (Join-Path $layout.PluginDir $src.Name) -Force
        $sib = Join-Path $src.DirectoryName ($src.BaseName + '.requirements.txt')
        if (Test-Path -LiteralPath $sib) { Copy-Item -LiteralPath $sib -Destination $layout.PluginDir -Force }
        $names += $src.BaseName
    } elseif ($src.Extension -eq '.zip') {
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $tmp = Join-Path $layout.PluginDir ('.install-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
        [IO.Compression.ZipFile]::ExtractToDirectory($src.FullName, $tmp)
        try {
            $entries = @(Get-ChildItem -LiteralPath $tmp | Where-Object { -not $_.Name.StartsWith('_') -and $_.Name -ne '__MACOSX' })
            if ($entries.Count -eq 0) { Fail "Empty plugin package: $Source" }
            foreach ($e in $entries) {
                $dst = Join-Path $layout.PluginDir $e.Name
                if ((Test-Path -LiteralPath $dst) -and -not $Force) { Fail "$dst already exists (use -Force to replace)." }
                if (Test-Path -LiteralPath $dst) { Remove-Item -LiteralPath $dst -Recurse -Force }
                Move-Item -LiteralPath $e.FullName -Destination $dst
                if ($e.PSIsContainer -or $e.Extension -eq '.py') { $names += ($e.Name -replace '\.py$', '') }
            }
        } finally {
            Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
        }
    } else {
        Fail "Give a plugin folder, a .py file, or a .zip package."
    }
    Write-VsOk "Copied to $($layout.PluginDir): $($names -join ', ')"
    Require-Python
    $failed = @()
    foreach ($n in $names) { $failed += Install-PluginDeps $layout.Python $n -AllowOnline:$Online }
    if (Service-Running) {
        Write-VsStep "Restarting the service so the new plugin is loaded"
        Invoke-Service 'restart' | Out-Null
    } else {
        Write-Host "  Start (or restart) the platform to load it: vsctl restart"
    }
    if ($failed.Count) { exit 2 }
}

function Read-ReleaseInfo([string]$Zip) {
    # 發行 zip：頂層一個資料夾 VisionSequence-<ver>\，裡面有 release.json
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [IO.Compression.ZipFile]::OpenRead($Zip)
    try {
        $entry = $archive.Entries | Where-Object { $_.FullName -match '^[^/\\]+[/\\]release\.json$' } | Select-Object -First 1
        if (-not $entry) { Fail "Not a VisionSequence release zip (no <top>/release.json): $Zip" }
        $reader = New-Object IO.StreamReader($entry.Open())
        try { $info = $reader.ReadToEnd() | ConvertFrom-Json } finally { $reader.Dispose() }
        $top = ($entry.FullName -split '[/\\]')[0]
        return @{ Version = [string]$info.version; Top = $top; Info = $info }
    } finally {
        $archive.Dispose()
    }
}

function Read-ReleaseInfoTree([string]$Tree) {
    $f = Join-Path $Tree 'release.json'
    if (-not (Test-Path -LiteralPath $f)) { Fail "Not a VisionSequence release tree (no release.json): $Tree" }
    $info = Get-Content -LiteralPath $f -Raw | ConvertFrom-Json
    return @{ Version = [string]$info.version; Top = (Split-Path -Leaf $Tree); Info = $info }
}

function Do-Update([string]$Zip) {
    if (-not $layout.Release) { Fail "update only applies to an installed station (<VS_HOME>\app\<ver> layout). In a checkout use git." }
    if (-not (Test-VsAdmin) -and -not $DryRun) { Fail "Run vsctl update from an elevated PowerShell (it restarts the service)." }
    if (-not (Test-Path -LiteralPath $Zip)) { Fail "Not found: $Zip" }
    $isTree = Test-Path -LiteralPath $Zip -PathType Container
    if ($isTree) { $rel = Read-ReleaseInfoTree $Zip } else { $rel = Read-ReleaseInfo $Zip }
    $newVer = $rel.Version
    $oldVer = $layout.Version
    $oldTree = Current-Target
    $newTree = Join-Path $appDir $newVer
    $oldPython = $layout.Python
    Write-VsStep "Update $oldVer -> $newVer"
    if ($newVer -eq $oldVer -and -not $Force) { Fail "Version $newVer is already installed and current (use -Force to reinstall)." }
    if ($rel.Info.sha256 -and $rel.Info.sha256_of) { }  # 保留：release.json 可帶內容清單
    $sumsFile = Join-Path (Split-Path -Parent $Zip) 'SHA256SUMS.txt'
    if (-not $isTree -and (Test-Path -LiteralPath $sumsFile)) {
        $expected = (Get-Content -LiteralPath $sumsFile | Where-Object { $_ -match [regex]::Escape((Split-Path -Leaf $Zip)) } | Select-Object -First 1)
        if ($expected) {
            $actual = (Get-FileHash -LiteralPath $Zip -Algorithm SHA256).Hash.ToLower()
            if (-not $expected.ToLower().StartsWith($actual)) { Fail "SHA256 mismatch for $Zip (SHA256SUMS.txt says otherwise). Download it again." }
            Write-VsOk "SHA256 verified"
        }
    }
    if ($DryRun) { Write-Host "  would extract $($rel.Top) to $newTree, reinstall plugin deps and DL pack, stop, migrate, switch current, start"; return }

    # 1. 備份（含 .env 與外掛）
    Require-Python
    New-Item -ItemType Directory -Force -Path (Join-Path $layout.DataDir 'backups') | Out-Null
    $backup = Join-Path $layout.DataDir ("backups\pre-update-$oldVer-to-$newVer.zip")
    Write-VsStep "Backup -> $backup"
    Invoke-VsManage $layout @('backup', '--out', $backup)
    if ($VsLastExit -ne 0) { Fail "Backup failed; update aborted." }
    $migBefore = Migration-Count $oldPython $layout.Current

    # 2. 解壓到 app\<ver>.partial 再改名（半途失敗不會留下看似完整的版本）；已解壓的樹就搬到 app\<ver>
    if ($isTree) {
        $src = (Resolve-Path -LiteralPath $Zip).Path.TrimEnd('\')
        if ($src -ine $newTree) {
            if (Test-Path -LiteralPath $newTree) { Remove-Item -LiteralPath $newTree -Recurse -Force }
            Move-Item -LiteralPath $src -Destination $newTree
        }
    } else {
        $partial = "$newTree.partial"
        if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Recurse -Force }
        if (Test-Path -LiteralPath $newTree) {
            if ($newTree -eq $oldTree) { Fail "Cannot replace the running version in place." }
            Remove-Item -LiteralPath $newTree -Recurse -Force
        }
        Write-VsStep "Extracting $(Split-Path -Leaf $Zip)"
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($Zip, $partial)
        $inner = Join-Path $partial $rel.Top
        if (-not (Test-Path -LiteralPath (Join-Path $inner 'python\python.exe'))) { Remove-Item -LiteralPath $partial -Recurse -Force; Fail "The release zip has no python\python.exe." }
        Move-Item -LiteralPath $inner -Destination $newTree
        Remove-Item -LiteralPath $partial -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not (Test-Path -LiteralPath (Join-Path $newTree 'python\python.exe'))) { Fail "$newTree has no python\python.exe." }
    $newPython = Join-Path $newTree 'python\python.exe'

    # 3. 舊版還在跑：先用新 python 裝外掛依賴與 DL 包（每個版本各自的 site-packages）
    $depFailed = Install-PluginDeps $newPython -AllowOnline:$Online
    $dlMarker = Join-Path $layout.Current 'DL-PACK.json'
    if (Test-Path -LiteralPath $dlMarker) {
        $marker = Get-Content -LiteralPath $dlMarker -Raw | ConvertFrom-Json
        $pack = Join-Path $packsDir ([string]$marker.file)
        if (Test-Path -LiteralPath $pack) {
            Write-VsStep "Reinstalling DL pack $($marker.file) into $newVer"
            Install-DlPack $pack $newTree $newPython -NoCheck
        } else {
            Write-VsWarn "DL pack $($marker.file) not found in $packsDir; run vsctl dl install <pack.zip> after the update."
        }
    }

    # 4. 停、migrate、切、起
    $wasRunning = Service-Running
    if (Service-Installed) { Write-VsStep "Stopping"; Invoke-Service 'stop' | Out-Null }
    Write-VsStep "Database migration"
    $env:VS_HOME = $layout.Home
    Push-Location $newTree
    try { & $newPython manage.py migrate --noinput; $mig = $LASTEXITCODE } finally { Pop-Location }
    if ($mig -ne 0) {
        Write-VsFail "migrate failed: keeping $oldVer, the new tree is left at $newTree.failed"
        Move-Item -LiteralPath $newTree -Destination "$newTree.failed" -Force
        if ($wasRunning) { Invoke-Service 'start' | Out-Null }
        exit 1
    }
    $migAfter = Migration-Count $newPython $newTree
    # 擷取端安裝檔：新版帶的比較新就換掉 data\downloads
    $clientSrc = Join-Path $newTree 'capture-client'
    if (Test-Path -LiteralPath (Join-Path $clientSrc 'manifest.json')) { Sync-CaptureClient $clientSrc }
    Set-Current $newTree
    Write-VsOk "current -> $newTree"
    Append-UpdateLog "update  $oldVer -> $newVer  migrations $migBefore -> $migAfter  backup $(Split-Path -Leaf $backup)"
    if ($wasRunning -or (Service-Installed)) {
        Write-VsStep "Starting"
        Invoke-Service 'start' | Out-Null
        $httpPort = [int](Get-VsSetting $layout 'VISION_HTTP_PORT' '8000')
        if (Wait-Healthy $httpPort $newVer) { Write-VsOk "healthz answered with $newVer" } else { Write-VsWarn "healthz did not answer within 60 s; check vsctl logs" }
    }
    $script:layout = Get-VsLayout
    Invoke-VsManage $script:layout @('doctor')
    Prune-Versions $Keep
    if ($depFailed.Count) { Write-VsWarn "Plugin dependencies still missing for: $($depFailed -join ', ')" }
    Write-VsOk "Update finished: $oldVer -> $newVer (rollback: vsctl rollback $oldVer)"
}

function Do-Rollback([string]$Target) {
    if (-not $layout.Release) { Fail "rollback only applies to an installed station." }
    if (-not (Test-VsAdmin)) { Fail "Run vsctl rollback from an elevated PowerShell." }
    if (-not $Target) { $Target = Previous-Version }
    if (-not $Target) { Fail "No previous version recorded in updates.log; give the version: vsctl rollback <version>" }
    $tree = Join-Path $appDir $Target
    if (-not (Test-Path -LiteralPath (Join-Path $tree 'python\python.exe'))) { Fail "Version $Target is not installed under $appDir." }
    $cur = $layout.Version
    if ($tree -eq (Current-Target)) { Fail "$Target is already current." }
    $wasRunning = Service-Running
    if (Service-Installed) { Write-VsStep "Stopping"; Invoke-Service 'stop' | Out-Null }
    $python = Join-Path $tree 'python\python.exe'
    $backup = Get-ChildItem -LiteralPath (Join-Path $layout.DataDir 'backups') -Filter "pre-update-$Target-to-*.zip" -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    $line = Get-Content -LiteralPath $updatesLog -ErrorAction SilentlyContinue | Where-Object { $_ -match "update\s+$([regex]::Escape($Target)) -> " } | Select-Object -Last 1
    $moved = $false
    if ($line -and $line -match 'migrations (\d+) -> (\d+)') { $moved = ([int]$Matches[2] -gt [int]$Matches[1]) }
    if ($RestoreDb) {
        if (-not $backup) { Fail "No pre-update backup for $Target in data\backups." }
        Write-VsStep "Restoring database from $($backup.Name)"
        $env:VS_HOME = $layout.Home
        Push-Location $tree
        try { & $python manage.py restore $backup.FullName --yes; $rc = $LASTEXITCODE } finally { Pop-Location }
        if ($rc -ne 0) { Fail "restore failed; nothing switched." }
    } elseif ($moved) {
        Write-VsWarn "The database was migrated after $Target; the old version may not start. Use: vsctl rollback $Target -RestoreDb (restores $($backup.Name))"
    }
    Set-Current $tree
    Append-UpdateLog "rollback  $cur -> $Target  restore_db $RestoreDb"
    Write-VsOk "current -> $tree"
    if ($wasRunning) { Invoke-Service 'start' | Out-Null }
}

function Prune-Versions([int]$KeepCount) {
    $current = Current-Target
    $prev = Previous-Version
    $all = Installed-Versions
    $candidates = @($all | Where-Object { $_.FullName -ne $current -and $_.Name -ne $prev })
    $remove = @($candidates | Select-Object -First ([Math]::Max(0, $candidates.Count - [Math]::Max(0, $KeepCount - 1))))
    foreach ($d in $remove) {
        Write-VsStep "Removing old version $($d.Name)"
        Remove-Item -LiteralPath $d.FullName -Recurse -Force
    }
    foreach ($d in Get-ChildItem -LiteralPath $appDir -Directory -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '\.(partial|failed)$' }) {
        Write-VsStep "Removing leftover $($d.Name)"
        Remove-Item -LiteralPath $d.FullName -Recurse -Force
    }
}

function Sync-CaptureClient([string]$Source) {
    # 版本樹帶的擷取端安裝檔比 data\downloads 的新才覆蓋（舊 zip 一起清掉）
    $dst = Join-Path $layout.DataDir 'downloads'
    $srcMan = Get-Content -LiteralPath (Join-Path $Source 'manifest.json') -Raw | ConvertFrom-Json
    $dstManFile = Join-Path $dst 'manifest.json'
    if (Test-Path -LiteralPath $dstManFile) {
        $dstMan = Get-Content -LiteralPath $dstManFile -Raw | ConvertFrom-Json
        $newer = $false
        try { $newer = ([version]$srcMan.version -gt [version]$dstMan.version) } catch { $newer = ([string]$srcMan.version -ne [string]$dstMan.version) }
        if (-not $newer) { return }
    }
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    Get-ChildItem -LiteralPath $dst -Filter 'VisionSequenceCapture-*.zip' -ErrorAction SilentlyContinue | Remove-Item -Force
    Copy-Item -Path (Join-Path $Source '*') -Destination $dst -Force
    Write-VsOk "Capture client $($srcMan.version) published to $dst (camera PCs update themselves)"
}

function Install-DlPack([string]$Pack, [string]$Tree, [string]$Python, [switch]$NoCheck) {
    if (-not (Test-Path -LiteralPath $Pack)) { Fail "Not found: $Pack" }
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $tmp = Join-Path $layout.DataDir ('tmp\dl-pack-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        [IO.Compression.ZipFile]::ExtractToDirectory($Pack, $tmp)
        $root = $tmp
        if (-not (Test-Path -LiteralPath (Join-Path $root 'dl-pack.json'))) {
            $sub = Get-ChildItem -LiteralPath $tmp -Directory | Select-Object -First 1
            if ($sub -and (Test-Path -LiteralPath (Join-Path $sub.FullName 'dl-pack.json'))) { $root = $sub.FullName } else { Fail "Not a VisionSequence DL pack (no dl-pack.json): $Pack" }
        }
        $meta = Get-Content -LiteralPath (Join-Path $root 'dl-pack.json') -Raw | ConvertFrom-Json
        $pyVer = (& $Python -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
        if ([string]$meta.python -ne $pyVer) { Fail "DL pack is built for Python $($meta.python), this installation runs $pyVer." }
        Write-VsStep "Installing DL pack $($meta.variant) (torch $($meta.torch), onnxruntime-gpu $($meta.onnxruntime)) into $Tree"
        if ($meta.variant -like 'cu*') {
            $smi = Get-Command nvidia-smi -ErrorAction SilentlyContinue
            if (-not $smi) { Write-VsWarn "nvidia-smi not found: no NVIDIA driver on this PC? The CUDA pack will fall back to CPU." }
        }
        $wheels = Join-Path $root 'wheels'
        # onnxruntime 與 onnxruntime-gpu 同名互蓋：先移除 CPU 版
        & $Python -m pip uninstall -y -q onnxruntime 2>$null | Out-Null
        # 先 torch（同一個 --no-index find-links 裡也要分兩步，避免 pip 從一般 wheel 解析到 CPU torch）
        & $Python -m pip install --disable-pip-version-check --no-index --find-links $wheels torch torchvision
        if ($LASTEXITCODE -ne 0) { Fail "torch install failed." }
        & $Python -m pip install --disable-pip-version-check --no-index --find-links $wheels -r (Join-Path $root 'requirements-dl.lock.txt')
        if ($LASTEXITCODE -ne 0) { Fail "DL requirements install failed." }
        $weightsSrc = Join-Path $root 'weights'
        if (Test-Path -LiteralPath $weightsSrc) {
            $assetDir = Get-VsSetting $layout 'VISION_ASSET_DIR' (Join-Path $layout.DataDir 'assets')
            $weightsDst = Join-Path $assetDir 'dl\weights'
            New-Item -ItemType Directory -Force -Path $weightsDst | Out-Null
            Copy-Item -Path (Join-Path $weightsSrc '*') -Destination $weightsDst -Force
            Write-VsOk "Weights copied to $weightsDst"
        }
        $ocrSrc = Join-Path $root 'ocr'
        if (Test-Path -LiteralPath $ocrSrc) {
            # OCR 模型（PP-OCRv4 ONNX）：manage.py ocr_models --install 也做得到；這裡順手裝進 ASSET_DIR\ocr
            $assetDir = Get-VsSetting $layout 'VISION_ASSET_DIR' (Join-Path $layout.DataDir 'assets')
            $ocrDst = Join-Path $assetDir 'ocr'
            New-Item -ItemType Directory -Force -Path $ocrDst | Out-Null
            Copy-Item -Path (Join-Path $ocrSrc '*') -Destination $ocrDst -Force
            Write-VsOk "OCR models copied to $ocrDst"
        }
        New-Item -ItemType Directory -Force -Path $packsDir | Out-Null
        $kept = Join-Path $packsDir (Split-Path -Leaf $Pack)
        if ((Resolve-Path -LiteralPath $Pack).Path -ne $kept) { Copy-Item -LiteralPath $Pack -Destination $kept -Force }
        $marker = @{ file = (Split-Path -Leaf $Pack); variant = [string]$meta.variant; torch = [string]$meta.torch; onnxruntime = [string]$meta.onnxruntime; installed_at = (Get-Date -Format 's') } | ConvertTo-Json
        [IO.File]::WriteAllText((Join-Path $Tree 'DL-PACK.json'), $marker, (New-Object Text.UTF8Encoding $false))
        Write-VsOk "DL pack recorded in $Tree\DL-PACK.json (reinstalled automatically by vsctl update)"
        if (-not $NoCheck) {
            $env:VS_HOME = $layout.Home
            $env:YOLO_OFFLINE = '1'
            Push-Location $Tree
            try { if ($Predict) { & $Python manage.py dl_check --predict } else { & $Python manage.py dl_check } } finally { Pop-Location }
        }
    } finally {
        Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}

function Show-Env {
    foreach ($k in ($layout.DotEnv.Keys | Sort-Object)) {
        $v = $layout.DotEnv[$k]
        if ($k -match 'KEY|SECRET|AUTH|PASSWORD|TOKEN') { if ($v.Length -gt 4) { $v = ('*' * 8) + $v.Substring($v.Length - 4) } elseif ($v) { $v = '****' } }
        Write-Host ("{0,-28} {1}" -f $k, $v)
    }
}

function Create-Admin([string]$Name) {
    if (-not $Name) { Fail "Usage: vsctl admin create <username> [-PasswordEnv NAME]" }
    Require-Python
    if ($PasswordEnv) {
        Invoke-VsManage $layout @('create_admin', $Name, '--password-env', $PasswordEnv)
    } else {
        $secure = Read-Host -Prompt "Password for $Name" -AsSecureString
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
        $env:VS_ADMIN_PASSWORD = $plain
        try { Invoke-VsManage $layout @('create_admin', $Name, '--password-env', 'VS_ADMIN_PASSWORD') } finally { Remove-Item Env:VS_ADMIN_PASSWORD -ErrorAction SilentlyContinue }
    }
    exit $script:VsLastExit
}

function Set-Firewall {
    if (-not (Test-VsAdmin)) { Fail "Run vsctl firewall from an elevated PowerShell." }
    $existing = Get-NetFirewallRule -DisplayName 'VisionSequence *' -ErrorAction SilentlyContinue
    if ($existing) { $existing | Remove-NetFirewallRule }
    if ($Remove) { Write-VsOk "Firewall rules removed"; return }
    $http = [int](Get-VsSetting $layout 'VISION_HTTP_PORT' '8000')
    $rules = @{}
    if (Test-Path -LiteralPath (Join-Path $layout.Home 'Caddyfile')) {
        $cf = Get-Content -LiteralPath (Join-Path $layout.Home 'Caddyfile') -Raw
        $httpsPort = 443
        if ($cf -match ':(\d+)\s*(,|\{)') { $httpsPort = [int]$Matches[1] }
        $rules['web (HTTPS)'] = $httpsPort
        if ($httpsPort -eq 443) { $rules['web redirect (HTTP)'] = 80 }
    } else {
        $rules['web (HTTP)'] = $http
    }
    $rules['TCP commands'] = [int](Get-VsSetting $layout 'VISION_TCP_PORT' '9000')
    $rules['capture clients'] = [int](Get-VsSetting $layout 'VISION_CAPTURE_PORT' '9100')
    foreach ($p in ($Ports -split '[,\s]+' | Where-Object { $_ })) { $rules["port $p"] = [int]$p }
    foreach ($name in $rules.Keys) {
        $splat = @{ DisplayName = "VisionSequence $name"; Direction = 'Inbound'; Protocol = 'TCP'; LocalPort = $rules[$name]; Action = 'Allow'; Profile = 'Any' }
        if ($Subnet) { $splat['RemoteAddress'] = ($Subnet -split '[,\s]+' | Where-Object { $_ }) }
        New-NetFirewallRule @splat | Out-Null
        Write-VsOk ("{0,-22} port {1}{2}" -f $name, $rules[$name], $(if ($Subnet) { " from $Subnet" } else { '' }))
    }
}

function Show-Logs {
    $file = Join-Path $layout.DataDir ($(if ($Proxy) { 'logs\proxy.log' } else { 'logs\service.log' }))
    if (-not (Test-Path -LiteralPath $file)) { Fail "No log yet: $file" }
    if ($Follow) { Get-Content -LiteralPath $file -Tail $Tail -Wait } else { Get-Content -LiteralPath $file -Tail $Tail }
}

switch ($Command.ToLower()) {
    'help' { Show-Help }
    '--help' { Show-Help }
    '-h' { Show-Help }
    'version' { Write-Host "VisionSequence $($layout.Version)  ($($layout.Current))"; if (Test-Path -LiteralPath (Join-Path $layout.Current 'DL-PACK.json')) { Write-Host ("DL pack: " + (Get-Content -LiteralPath (Join-Path $layout.Current 'DL-PACK.json') -Raw)) } }
    'start' { exit (Invoke-Service 'start') }
    'stop' { exit (Invoke-Service 'stop') }
    'restart' { exit (Invoke-Service 'restart') }
    'status' { Invoke-Service 'status' | Out-Null; $code = $LASTEXITCODE; if (Test-Path -LiteralPath (Join-Path $layout.Home 'Caddyfile')) { Invoke-Proxy 'status' | Out-Null }; exit $code }
    'run' {
        Require-Python
        $bind = '0.0.0.0'
        if ((Get-VsSetting $layout 'BEHIND_HTTPS_PROXY' '0') -match '^(1|true|yes)$') { $bind = '127.0.0.1' }
        if (Service-Running) { Fail "The service is running; stop it first (vsctl stop) or the ports are taken." }
        $pidFile = Join-Path $layout.DataDir 'run\serve.pid'
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $pidFile) | Out-Null
        Invoke-VsManage $layout (@('serve', '--host', $bind, '--pid-file', $pidFile) + $Rest); exit $VsLastExit
    }
    'logs' { Show-Logs }
    'doctor' { Require-Python; $a = @('doctor'); if ($Json) { $a += '--json' }; Invoke-VsManage $layout ($a + $Rest); exit $VsLastExit }
    'backup' {
        # PowerShell 會把 --out 當成自己的 -Out 參數（與 -OutVariable 撞名），所以目標路徑走 -Out；其餘 --with-images 等原樣透傳
        Require-Python; $a = @('backup'); if ($Out) { $a += @('--out', $Out) }; if ($Sub) { $a += $Sub }; Invoke-VsManage $layout ($a + $Rest); exit $VsLastExit
    }
    'purge' { Require-Python; $a = @('purge'); if ($Sub) { $a += $Sub }; Invoke-VsManage $layout ($a + $Rest); exit $VsLastExit }
    'restore' {
        if (-not $Sub) { Fail "Usage: vsctl restore <backup.zip>" }
        Require-Python
        if (-not (Test-VsAdmin)) { Fail "Run vsctl restore from an elevated PowerShell (it stops the service)." }
        $wasRunning = Service-Running
        if (Service-Installed) { Invoke-Service 'stop' | Out-Null }
        Invoke-VsManage $layout @('restore', (Resolve-Path -LiteralPath $Sub).Path, '--yes')
        $rc = $VsLastExit
        if ($rc -eq 0) { Invoke-VsManage $layout @('migrate', '--noinput'); $rc = $VsLastExit }
        if ($wasRunning) { Invoke-Service 'start' | Out-Null }
        exit $rc
    }
    'manage' { Require-Python; $a = @(); if ($Sub) { $a += $Sub }; Invoke-VsManage $layout ($a + $Rest); exit $VsLastExit }
    'update' { if (-not $Sub) { Fail "Usage: vsctl update <VisionSequence-<ver>-win64.zip> [-Keep N] [-Online]" }; Do-Update (Resolve-Path -LiteralPath $Sub).Path }
    'rollback' { Do-Rollback $Sub }
    'versions' {
        if ($Sub -eq 'prune') { if (-not (Test-VsAdmin)) { Fail "Run from an elevated PowerShell." }; Prune-Versions $Keep; break }
        $cur = Current-Target
        $prev = Previous-Version
        foreach ($d in Installed-Versions) {
            $tag = ''
            if ($d.FullName -eq $cur) { $tag = '  <- current' } elseif ($d.Name -eq $prev) { $tag = '  (previous, rollback target)' }
            $dl = ''
            if (Test-Path -LiteralPath (Join-Path $d.FullName 'DL-PACK.json')) { $dl = '  [DL]' }
            Write-Host ("{0,-12} {1}{2}{3}" -f $d.Name, $d.LastWriteTime.ToString('yyyy-MM-dd'), $dl, $tag)
        }
        if (Test-Path -LiteralPath $updatesLog) { Write-Host "--- updates.log"; Get-Content -LiteralPath $updatesLog -Tail 5 }
    }
    'plugins' {
        switch ($Sub.ToLower()) {
            'list' { Require-Python; $a = @('plugins', '--list'); if ($Json) { $a += '--json' }; Invoke-VsManage $layout $a; exit $VsLastExit }
            'install' { if ($Rest.Count -lt 1) { Fail "Usage: vsctl plugins install <zip|folder|file.py> [-Online] [-Force]" }; Install-Plugin (Resolve-Path -LiteralPath $Rest[0]).Path }
            'deps' { Require-Python; $only = ''; if ($Rest.Count) { $only = $Rest[0] }; $f = Install-PluginDeps $layout.Python $only -AllowOnline:$Online; if ($f.Count) { exit 2 } }
            'rescan' {
                $http = [int](Get-VsSetting $layout 'VISION_HTTP_PORT' '8000')
                $key = Get-VsSetting $layout 'VISION_API_KEY' ''
                try {
                    $r = Invoke-WebRequest -UseBasicParsing -Method Post -Uri "http://127.0.0.1:$http/api/vision/plugins/rescan" -Headers @{ 'X-API-Key' = $key } -TimeoutSec 30
                    Write-Host $r.Content
                } catch { Fail "rescan failed: $($_.Exception.Message). Is the service running? (Changed files still need vsctl restart.)" }
            }
            default { Fail "Usage: vsctl plugins list | install <zip|folder> | deps [<name>] [-Online] | rescan" }
        }
    }
    'dl' {
        Require-Python
        switch ($Sub.ToLower()) {
            'check' { $a = @('dl_check'); if ($Predict) { $a += '--predict' }; $env:YOLO_OFFLINE = '1'; Invoke-VsManage $layout $a; exit $VsLastExit }
            'install' {
                if ($Rest.Count -lt 1) { Fail "Usage: vsctl dl install <VisionSequence-DL-<variant>-<ver>.zip> [-Predict]" }
                Install-DlPack (Resolve-Path -LiteralPath $Rest[0]).Path $layout.Current $layout.Python
                if (Service-Running) { Write-VsStep "Restarting so the tools pick up the new packages"; Invoke-Service 'restart' | Out-Null }
            }
            default { Fail "Usage: vsctl dl check [-Predict] | dl install <pack.zip> [-Predict]" }
        }
    }
    'env' {
        switch ($Sub.ToLower()) {
            'list' { Show-Env }
            'get' { if ($Rest.Count -lt 1) { Fail "Usage: vsctl env get KEY" }; if ($layout.DotEnv.ContainsKey($Rest[0])) { Write-Output $layout.DotEnv[$Rest[0]] } else { exit 1 } }
            'set' {
                if ($Rest.Count -lt 1 -or $Rest[0] -notmatch '^([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { Fail "Usage: vsctl env set KEY=VALUE" }
                Set-VsDotEnv $layout.EnvFile $Matches[1] $Matches[2]
                Write-VsOk "$($Matches[1]) set in $($layout.EnvFile) (takes effect after vsctl restart)"
            }
            default { Fail "Usage: vsctl env list | get KEY | set KEY=VALUE" }
        }
    }
    'admin' { if ($Sub -ne 'create') { Fail "Usage: vsctl admin create <username> [-PasswordEnv NAME]" }; $n = ''; if ($Rest.Count) { $n = $Rest[0] }; Create-Admin $n }
    'service' {
        if ($Sub -notin @('install', 'uninstall', 'start', 'stop', 'restart', 'status')) { Fail "Usage: vsctl service install|uninstall|start|stop|restart|status [-Mode service|task] [-User -Password] [-Interactive]" }
        $extra = @{}
        if ($Sub -eq 'install' -and (Test-Path -LiteralPath (Join-Path $layout.Home 'Caddyfile'))) { $extra['BindHost'] = '127.0.0.1' }
        exit (Invoke-Service $Sub $extra)
    }
    'proxy' {
        if ($Sub -notin @('configure', 'install', 'uninstall', 'start', 'stop', 'restart', 'status', 'export-root', 'trust')) { Fail "Usage: vsctl proxy configure|install|uninstall|start|stop|restart|status|export-root|trust" }
        if ($Sub -eq 'configure' -and $Https) {
            # 代理開關要跟 .env 與服務綁定位址一致
            Set-VsDotEnv $layout.EnvFile 'BEHIND_HTTPS_PROXY' $(if ($Https -eq 'none') { '0' } else { '1' })
        }
        exit (Invoke-Proxy $Sub)
    }
    'firewall' { Set-Firewall }
    'certs' {
        switch ($Sub.ToLower()) {
            'export' { exit (Invoke-Proxy 'export-root') }
            'import' { exit (Invoke-Proxy 'trust') }
            default { Fail "Usage: vsctl certs export [-Out root.crt] | import [-File root.crt]" }
        }
    }
    default { Write-VsFail "Unknown command: $Command"; Show-Help; exit 2 }
}
