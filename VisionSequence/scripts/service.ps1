<#
.SYNOPSIS
    Run the VisionSequence API (and the HTTPS proxy) as a Windows service (NSSM) or a scheduled task.

.DESCRIPTION
    service.ps1 <install|uninstall|start|stop|restart|status> [-Component api|proxy] [-Mode service|task] ...

    -Mode service (default) uses tools\nssm.exe: real service, delayed auto-start, log rotation, and a Ctrl-C stop so
    uvicorn shuts down cleanly (Modbus slave, WAL, SSE). -Mode task registers a scheduled task instead (no NSSM; use
    -Interactive when the server PC itself runs SDK cameras that need a logged-on session).
    The service points at <VS_HOME>\current so an update only swaps the junction.

.EXAMPLE
    .\scripts\service.ps1 install                       # NSSM service "VisionSequence" as LocalSystem
    .\scripts\service.ps1 install -BindHost 127.0.0.1   # behind the HTTPS proxy
    .\scripts\service.ps1 install -Component proxy      # Caddy (after proxy.ps1 configure)
    .\scripts\service.ps1 install -Mode task -Interactive -User PLANT\vision -Password ****
    .\scripts\service.ps1 status
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)][ValidateSet('install', 'uninstall', 'start', 'stop', 'restart', 'status')][string]$Action = 'status',
    [ValidateSet('api', 'proxy')][string]$Component = 'api',
    [ValidateSet('service', 'task')][string]$Mode = 'service',
    [string]$Name = '',
    [string]$User = 'LocalSystem',
    [string]$Password = '',
    [int]$Port = 0,
    [string]$BindHost = '',
    [switch]$Interactive,
    [string]$Nssm = '',
    [switch]$DryRun,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'vslib.ps1')
$layout = Get-VsLayout
if ($Uninstall) { $Action = 'uninstall' }
if (-not $Name) { if ($Component -eq 'proxy') { $Name = 'VisionSequenceProxy' } else { $Name = 'VisionSequence' } }
if ($User -eq 'SYSTEM') { $User = 'LocalSystem' }
if ($Port -le 0) { $Port = [int](Get-VsSetting $layout 'VISION_HTTP_PORT' '8000') }
if (-not $BindHost) {
    $BindHost = '0.0.0.0'
    if ((Get-VsSetting $layout 'BEHIND_HTTPS_PROXY' '0') -match '^(1|true|yes)$') { $BindHost = '127.0.0.1' }
}
$logDir = Join-Path $layout.DataDir 'logs'
$runDir = Join-Path $layout.DataDir 'run'
$pidFile = Join-Path $runDir 'serve.pid'
$logFile = Join-Path $logDir ($(if ($Component -eq 'proxy') { 'proxy.log' } else { 'service.log' }))

function Invoke-Nssm([string[]]$Arguments) {
    if ($DryRun) { Write-Host ("  nssm " + ($Arguments -join ' ')) -ForegroundColor DarkGray; return }
    # NSSM 的 stdout 是 UTF-16，直接顯示會夾 NUL；這裡只看離開碼。
    $p = Start-Process -FilePath $script:nssmExe -ArgumentList $Arguments -NoNewWindow -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "nssm $($Arguments[0]) failed (exit $($p.ExitCode)): nssm $($Arguments -join ' ')" }
}

function Get-ServiceState([string]$svc) {
    $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
    if ($s) { return $s.Status.ToString() }
    return ''
}

function Get-TaskState([string]$task) {
    $t = Get-ScheduledTask -TaskName $task -ErrorAction SilentlyContinue
    if ($t) { return $t.State.ToString() }
    return ''
}

function Assert-Admin {
    if (-not $DryRun -and -not (Test-VsAdmin)) { throw "Run this from an elevated (Administrator) PowerShell." }
}

function Resolve-Nssm {
    $script:nssmExe = Find-VsTool $layout 'nssm.exe' $Nssm
    if (-not $script:nssmExe) {
        if ($DryRun) { $script:nssmExe = 'nssm.exe'; return }
        throw "nssm.exe not found (expected in $($layout.ToolsDir) or on PATH). The release build ships it; in a checkout use -Mode task or download NSSM 2.24."
    }
}

function Get-ProgramAndArgs {
    if ($Component -eq 'proxy') {
        $caddy = Find-VsTool $layout 'caddy.exe'
        if (-not $caddy) { if ($DryRun) { $caddy = (Join-Path $layout.ToolsDir 'caddy.exe') } else { throw "caddy.exe not found in $($layout.ToolsDir). Run the release build or download Caddy 2 into tools\." } }
        $caddyfile = Join-Path $layout.Home 'Caddyfile'
        if (-not $DryRun -and -not (Test-Path -LiteralPath $caddyfile)) { throw "No Caddyfile at $caddyfile. Run scripts\proxy.ps1 configure first." }
        return @{ Program = $caddy; Args = @('run', '--config', $caddyfile, '--adapter', 'caddyfile'); Dir = $layout.Home
                  Env = @("XDG_DATA_HOME=" + (Join-Path $layout.DataDir 'caddy'), "XDG_CONFIG_HOME=" + (Join-Path $layout.DataDir 'caddy'), "HOME=" + (Join-Path $layout.DataDir 'caddy')) }
    }
    $py = $layout.Python
    if (-not $py) { if ($DryRun) { $py = (Join-Path $layout.Current 'python\python.exe') } else { throw "No Python under $($layout.Current). Release: python\python.exe; checkout: run scripts\dev.ps1 -Setup." } }
    return @{ Program = $py; Args = @('manage.py', 'serve', '--host', $BindHost, '--port', "$Port", '--pid-file', $pidFile); Dir = $layout.Current
              Env = @("VS_HOME=" + $layout.Home, 'PYTHONIOENCODING=utf-8', 'PYTHONUTF8=1', 'PYTHONUNBUFFERED=1', 'YOLO_OFFLINE=1') }
}

function Install-AsService {
    Assert-Admin
    Resolve-Nssm
    $spec = Get-ProgramAndArgs
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $logDir, $runDir | Out-Null }
    if (Get-ServiceState $Name) {
        Write-VsStep "Service $Name exists: stopping and re-applying settings"
        Invoke-Nssm @('stop', $Name)
        Invoke-Nssm @('set', $Name, 'Application', $spec.Program)
        Invoke-Nssm (@('set', $Name, 'AppParameters') + @(($spec.Args -join ' ')))
    } else {
        Write-VsStep "Installing service $Name"
        Invoke-Nssm (@('install', $Name, $spec.Program) + $spec.Args)
    }
    Invoke-Nssm @('set', $Name, 'AppDirectory', $spec.Dir)
    Invoke-Nssm (@('set', $Name, 'AppEnvironmentExtra') + $spec.Env)
    Invoke-Nssm @('set', $Name, 'DisplayName', $(if ($Component -eq 'proxy') { 'VisionSequence HTTPS proxy' } else { 'VisionSequence machine vision platform' }))
    Invoke-Nssm @('set', $Name, 'Description', $(if ($Component -eq 'proxy') { 'Caddy reverse proxy: TLS termination for the VisionSequence web interface.' } else { 'VisionSequence API, TCP command port, capture hub and Modbus. Logs in data\logs.' }))
    Invoke-Nssm @('set', $Name, 'Start', 'SERVICE_DELAYED_AUTO_START')
    Invoke-Nssm @('set', $Name, 'AppStdout', $logFile)
    Invoke-Nssm @('set', $Name, 'AppStderr', $logFile)
    Invoke-Nssm @('set', $Name, 'AppRotateFiles', '1')
    Invoke-Nssm @('set', $Name, 'AppRotateOnline', '1')
    Invoke-Nssm @('set', $Name, 'AppRotateBytes', '20971520')
    Invoke-Nssm @('set', $Name, 'AppRestartDelay', '5000')
    Invoke-Nssm @('set', $Name, 'AppExit', 'Default', 'Restart')
    # 停止順序：Ctrl-C（uvicorn 正常關閉，最多 15 秒）→ 關視窗 → 執行緒 → 強制
    Invoke-Nssm @('set', $Name, 'AppStopMethodSkip', '0')
    Invoke-Nssm @('set', $Name, 'AppStopMethodConsole', '15000')
    Invoke-Nssm @('set', $Name, 'AppStopMethodWindow', '2000')
    Invoke-Nssm @('set', $Name, 'AppStopMethodThreads', '2000')
    if ($Component -eq 'proxy') { Invoke-Nssm @('set', $Name, 'DependOnService', 'VisionSequence') }
    if ($User -ne 'LocalSystem') {
        if (-not $Password) { throw "A password is required when -User is not LocalSystem." }
        Invoke-Nssm @('set', $Name, 'ObjectName', $User, $Password)
        if (-not $DryRun) {
            # 非 SYSTEM 帳號要能寫資料、外掛與 .env
            foreach ($p in @($layout.DataDir, $layout.PluginDir, $layout.EnvFile)) {
                if (Test-Path -LiteralPath $p) { & icacls $p /grant "${User}:(OI)(CI)M" /T /Q | Out-Null }
            }
        }
    }
    Invoke-Nssm @('start', $Name)
    if (-not $DryRun) { Start-Sleep -Seconds 3 }
    Write-VsOk "Service $Name installed (state: $(Get-ServiceState $Name))"
    Write-Host "  Log: $logFile"
}

function Uninstall-AsService {
    Assert-Admin
    if (-not (Get-ServiceState $Name)) { Write-VsWarn "Service $Name is not installed."; return }
    Resolve-Nssm
    Invoke-Nssm @('stop', $Name)
    Invoke-Nssm @('remove', $Name, 'confirm')
    Write-VsOk "Service $Name removed"
}

function Install-AsTask {
    Assert-Admin
    if ($Component -eq 'proxy') { throw "The proxy only runs as a service (-Mode service)." }
    $spec = Get-ProgramAndArgs
    if (-not $DryRun) { New-Item -ItemType Directory -Force -Path $logDir, $runDir | Out-Null }
    $runner = Join-Path $layout.Home 'run-service.ps1'
    $quotedArgs = ($spec.Args | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }) -join ' '
    $wrapper = @"
# Generated by service.ps1 (task mode) - starts the API process and rotates its log.
`$ErrorActionPreference = 'Continue'
`$env:VS_HOME = '$($layout.Home)'
`$env:PYTHONIOENCODING = 'utf-8'
`$env:PYTHONUTF8 = '1'
`$env:YOLO_OFFLINE = '1'
`$log = '$logFile'
`$logDir = '$logDir'
if ((Test-Path `$log) -and ((Get-Item `$log).Length -gt 20MB)) {
    Move-Item `$log (Join-Path `$logDir ('service-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.log')) -Force
    Get-ChildItem `$logDir -Filter 'service-*.log' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 10 | Remove-Item -Force
}
Set-Location '$($spec.Dir)'
& '$($spec.Program)' $quotedArgs *>> `$log
"@
    if ($DryRun) {
        Write-Host "  would write $runner and register scheduled task $Name (user $User, interactive=$Interactive)" -ForegroundColor DarkGray
        Write-Host $wrapper -ForegroundColor DarkGray
        return
    }
    [IO.File]::WriteAllText($runner, $wrapper, (New-Object Text.UTF8Encoding $true))
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$runner`"" -WorkingDirectory $spec.Dir
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
    $desc = 'VisionSequence machine vision platform'
    if ($Interactive) {
        if ($User -eq 'LocalSystem') { throw "-Interactive needs a real user account (-User DOMAIN\name): SDK cameras need that user's desktop session." }
        $trigger = New-ScheduledTaskTrigger -AtLogOn -User $User
        $principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Highest
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $desc -Force | Out-Null
        Write-VsOk "Scheduled task $Name registered: starts when $User signs in (interactive session for SDK cameras)."
        Write-VsWarn "Enable automatic sign-in for $User (or keep the PC signed in), otherwise the platform is not running after a reboot."
    } elseif ($User -eq 'LocalSystem') {
        $trigger = New-ScheduledTaskTrigger -AtStartup
        $principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description $desc -Force | Out-Null
    } else {
        if (-not $Password) { throw "A password is required when -User is not LocalSystem." }
        $trigger = New-ScheduledTaskTrigger -AtStartup
        Register-ScheduledTask -TaskName $Name -Action $action -Trigger $trigger -Settings $settings -User $User -Password $Password -RunLevel Highest -Description $desc -Force | Out-Null
    }
    Start-ScheduledTask -TaskName $Name
    Start-Sleep -Seconds 3
    Write-VsOk "Scheduled task $Name registered and started (state: $(Get-TaskState $Name))"
    Write-Host "  Log: $logFile"
}

function Uninstall-AsTask {
    Assert-Admin
    if (-not (Get-TaskState $Name)) { Write-VsWarn "Scheduled task $Name is not registered."; return }
    Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    Stop-ServeProcess
    Write-VsOk "Scheduled task $Name removed"
}

function Stop-ServeProcess {
    # task 模式沒有服務控制器：用 pid 檔停 uvicorn（serve --pid-file），沒有就用命令列找。
    if (Test-Path -LiteralPath $pidFile) {
        $procId = 0
        try { $procId = [int]((Get-Content -LiteralPath $pidFile -Raw).Trim()) } catch { $procId = 0 }
        if ($procId -gt 0) {
            $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
            if ($p) { Stop-Process -Id $procId -Force; Write-VsOk "Stopped serve process $procId" }
        }
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }
}

$script:modeGiven = $PSBoundParameters.ContainsKey('Mode')

function Detect-Mode {
    # 沒指定時，看哪一種已經裝了
    if ($script:modeGiven) { return $Mode }
    if (Get-ServiceState $Name) { return 'service' }
    if (Get-TaskState $Name) { return 'task' }
    return $Mode
}

function Show-Status {
    $svc = Get-ServiceState $Name
    $task = Get-TaskState $Name
    Write-Host "VisionSequence $($layout.Version)  home: $($layout.Home)"
    if ($layout.Release) { Write-Host "  current -> $((Get-Item -LiteralPath $layout.Current -ErrorAction SilentlyContinue).Target)" }
    if ($svc) { Write-Host "  service $Name`: $svc" } elseif ($task) { Write-Host "  task $Name`: $task" } else { Write-Host "  $Name`: not installed (service or task)" }
    if ($Component -eq 'api') {
        $proxy = Get-ServiceState 'VisionSequenceProxy'
        if ($proxy) { Write-Host "  service VisionSequenceProxy: $proxy" }
        $procId = 0
        if (Test-Path -LiteralPath $pidFile) { try { $procId = [int]((Get-Content -LiteralPath $pidFile -Raw).Trim()) } catch { $procId = 0 } }
        if ($procId -gt 0) {
            $alive = Get-Process -Id $procId -ErrorAction SilentlyContinue
            Write-Host "  serve pid: $procId $(if ($alive) { '(running)' } else { '(stale pid file)' })"
        }
        $health = Get-VsHealth $Port
        if ($health) { Write-Host "  http://127.0.0.1:$Port/healthz -> $($health.status) $($health.version)" -ForegroundColor Green } else { Write-Host "  http://127.0.0.1:$Port/healthz -> not responding" -ForegroundColor Yellow }
        $tcp = [int](Get-VsSetting $layout 'VISION_TCP_PORT' '9000')
        $cap = [int](Get-VsSetting $layout 'VISION_CAPTURE_PORT' '9100')
        $ports = @{ $Port = 'http'; $tcp = 'tcp commands'; $cap = 'capture'; 443 = 'https' }
        $listening = Get-VsListening ([int[]]$ports.Keys)
        Write-Host ("  listening: " + (($ports.Keys | Sort-Object | ForEach-Object { "$_ $($ports[$_])=" + $(if ($listening -contains $_) { 'yes' } else { 'no' }) }) -join ', '))
        Write-Host "  log: $logFile"
    }
    if (-not $svc -and -not $task) { return 1 }
    return 0
}

switch ($Action) {
    'install' { if ($Mode -eq 'service') { Install-AsService } else { Install-AsTask } }
    'uninstall' { if ((Detect-Mode) -eq 'service') { Uninstall-AsService } else { Uninstall-AsTask } }
    'start' {
        Assert-Admin
        if ((Detect-Mode) -eq 'service') { Resolve-Nssm; Invoke-Nssm @('start', $Name) } else { Start-ScheduledTask -TaskName $Name }
        if (-not $DryRun) { Start-Sleep -Seconds 3; Show-Status | Out-Null }
    }
    'stop' {
        Assert-Admin
        if ((Detect-Mode) -eq 'service') { Resolve-Nssm; Invoke-Nssm @('stop', $Name) } else { Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue; Stop-ServeProcess }
        Write-VsOk "$Name stopped"
    }
    'restart' {
        Assert-Admin
        if ((Detect-Mode) -eq 'service') { Resolve-Nssm; Invoke-Nssm @('restart', $Name) } else { Stop-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue; Stop-ServeProcess; Start-ScheduledTask -TaskName $Name }
        if (-not $DryRun) { Start-Sleep -Seconds 3; Show-Status | Out-Null }
    }
    'status' { $code = Show-Status; exit $code }
}
