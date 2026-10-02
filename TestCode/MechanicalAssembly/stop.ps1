$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

# 埠號以 vite.config.js 為準，避免兩處設定不一致
$port = 6001
$config = Get-Content -LiteralPath 'vite.config.js' -Raw -Encoding UTF8
if ($config -match 'port:\s*(\d+)') { $port = [int]$Matches[1] }

$listeners = @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
if (-not $listeners.Count) {
    Write-Host "連接埠 $port 沒有執行中的服務。"
    exit 0
}

$projectRoot = (Resolve-Path -LiteralPath $PSScriptRoot).Path
foreach ($processId in ($listeners.OwningProcess | Sort-Object -Unique)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId"
    if (-not $process) { continue }
    # 只停止本專案的 Vite 服務，其他程式佔用此埠時不動它
    $commandLine = [string]$process.CommandLine
    $isProjectVite = $process.Name -ieq 'node.exe' -and $commandLine -match 'vite' -and
        $commandLine.IndexOf($projectRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0
    if (-not $isProjectVite) {
        Write-Warning "連接埠 $port 由其他程式使用（PID $processId，$($process.Name)），未停止。"
        continue
    }
    # 連同子程序（esbuild）一起結束
    & taskkill.exe /PID $processId /T /F | Out-Null
    Write-Host "已停止 Assembly Studio 服務（PID $processId，連接埠 $port）。"
}
