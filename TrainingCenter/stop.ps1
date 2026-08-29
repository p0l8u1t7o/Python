# 停止 start.ps1 啟動的 Django 與 Vite（含所有子程序），並釋放 8001 / 5174。
param([switch]$Quiet)

$root = $PSScriptRoot
$runDir = Join-Path $root '.run'

function Say($msg, $color = 'Green') { if (-not $Quiet) { Write-Host $msg -ForegroundColor $color } }

function Stop-Tree($procId) {
    # taskkill /T 會連同整棵子程序樹（cmd → node → esbuild、python autoreloader）一起結束
    if (Get-Process -Id $procId -ErrorAction SilentlyContinue) {
        & taskkill.exe /PID $procId /T /F 2>&1 | Out-Null
        return $true
    }
    return $false
}

foreach ($name in 'backend', 'frontend') {
    $pidFile = Join-Path $runDir "$name.pid"
    if (Test-Path $pidFile) {
        $procId = [int](Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
        if (Stop-Tree $procId) { Say "已停止 $name (PID $procId)" } else { Say "$name (PID $procId) 已不在執行" 'DarkGray' }
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    }
}

# 保險：清掉仍佔用 8001 / 5174 的程序（例如手動啟動、或 PID 檔遺失）
foreach ($port in 8001, 5174) {
    $owners = @()
    try {
        $owners = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop | Select-Object -ExpandProperty OwningProcess -Unique
    } catch {
        # 沒有 Get-NetTCPConnection 時退回 netstat
        $owners = (netstat -ano | Select-String ":$port\s.*LISTENING\s+(\d+)") | ForEach-Object { $_.Matches[0].Groups[1].Value } | Select-Object -Unique
    }
    foreach ($o in $owners) {
        if ($o -and $o -ne 0 -and (Stop-Tree ([int]$o))) { Say "已釋放埠 $port (PID $o)" }
    }
}
Say '完成。'
