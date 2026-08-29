# 停止 dev.ps1 啟動的行程
$root = Split-Path -Parent $PSScriptRoot
$pidFile = "$root\logs\dev.pids"
if (Test-Path $pidFile) {
    foreach ($id in (Get-Content $pidFile) -split " ") {
        if ($id) {
            try { Stop-Process -Id ([int]$id) -Force -ErrorAction Stop; Write-Host "已停止 $id" } catch {}
            # cmd.exe 啟動的 node 子行程
            Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq [int]$id } | ForEach-Object {
                try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
            }
        }
    }
    Remove-Item $pidFile -Force
}
# 保險：殘留的 vite / serve
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*manage.py serve*" -or ($_.CommandLine -like "*vite*" -and $_.CommandLine -like "*VisionSequence*") } | ForEach-Object {
    try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; Write-Host "已停止 $($_.ProcessId)" } catch {}
}
