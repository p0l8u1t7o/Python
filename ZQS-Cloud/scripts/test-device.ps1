<#
.SYNOPSIS
    Tests a device against the platform's MQTT rules. One command, no setup.

.DESCRIPTION
    A thin wrapper over scripts\run_device_test.py. It picks the project
    virtualenv for you, so nothing needs activating first.

    Run it with no arguments and it does the sensible thing: self-test first,
    then wait for your device. That order matters. The self-test proves the
    tool itself is sound - a harness that always says "pass" looks identical to
    a working one right up until it waves a broken device through.

.PARAMETER SelfTest
    Only verify the tool. Runs a correct reference device (must pass
    everything) and several deliberately broken ones (each must be caught).

.PARAMETER Device
    Only test a real device. Skips the self-test - use this once you have
    already run it today.

.PARAMETER DeviceId
    The device_id you expect to connect. Needed to send commands.

.PARAMETER Port
    Listening port. Default 1883.

.PARAMETER Timeout
    Seconds to wait for the device before giving up. Default 300.

.PARAMETER Duration
    Seconds to keep testing after the device connects. 0 waits for Ctrl+C.

.PARAMETER Command
    A command to send once the device has subscribed, e.g. set_power_limit.

.PARAMETER Params
    JSON parameters for -Command. PowerShell passes single-quoted strings
    through unchanged, so: -Params '{"limit_w": 400000}'

.PARAMETER Interactive
    Type commands by hand while the test runs.

.EXAMPLE
    .\scripts\test-device.ps1
    Self-test, then wait for a device. Start here.

.EXAMPLE
    .\scripts\test-device.ps1 -SelfTest
    Just prove the tool works.

.EXAMPLE
    .\scripts\test-device.ps1 -Device -DeviceId ZQS-BESS-0001 -Command set_power_limit -Params '{"limit_w": 400000}'
    Test a real device and exercise the downlink path.

.NOTES
    Exit codes:
      0    passed
      1    failed - the device does not conform, or the self-test found the
           tool disagreeing with what it should report
      2    could not run - bad arguments, port in use, no credentials
      3    incomplete - nothing connected, or a required behaviour never
           happened
      130  interrupted
#>
[CmdletBinding()]
param(
    [switch]$SelfTest,
    [switch]$Device,
    [string]$DeviceId = '',
    [int]$Port = 1883,
    [double]$Timeout = 300,
    [double]$Duration = 0,
    [string]$Command = '',
    [string]$Params = '{}',
    [switch]$Interactive,
    [switch]$NoReport
)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$script = Join-Path $root 'scripts\run_device_test.py'

# The launcher re-execs itself into .venv, so any Python that can start it will
# do. Prefer the venv anyway to skip a process hop.
function Get-Python {
    $venv = Join-Path $root '.venv\Scripts\python.exe'
    if (Test-Path $venv) { return $venv }
    foreach ($name in @('py', 'python')) {
        if (Get-Command $name -ErrorAction SilentlyContinue) { return $name }
    }
    throw 'Python not found. Run: .\scripts\dev.ps1 -Setup'
}

$python = Get-Python

# Chinese output turns into mojibake if the console is left on a legacy code
# page, and the child cannot fix a code page it did not set.
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }
$env:PYTHONIOENCODING = 'utf-8'

function Invoke-Launcher {
    param([string[]]$LauncherArgs)

    # A native command's stderr becomes a terminating ErrorRecord under
    # $ErrorActionPreference = 'Stop'. Judge it by its exit code instead -
    # that is the whole point of having exit codes.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $python $script @LauncherArgs
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

$runSelfTest = $SelfTest -or (-not $Device)
$runDevice = $Device -or (-not $SelfTest)

if ($runSelfTest) {
    $selfArgs = @('self-test')
    if ($NoReport) { $selfArgs += '--no-report' }

    $code = Invoke-Launcher $selfArgs
    if ($code -ne 0) {
        Write-Host ''
        Write-Host '測試工具自我驗證沒過，因此不會繼續測設備。' -ForegroundColor Red
        Write-Host '在修好之前，它的報告不能當作驗收依據。' -ForegroundColor Red
        exit $code
    }

    if ($runDevice) {
        Write-Host ''
        Write-Host '工具驗證通過。接下來等你的設備連進來。' -ForegroundColor Green
        Write-Host '請現在啟動 LabVIEW（或你的設備），連到這台電腦的 ' -NoNewline
        Write-Host "$Port" -ForegroundColor Cyan -NoNewline
        Write-Host ' 埠。'
        Write-Host ''
    }
}

if (-not $runDevice) { exit 0 }

$deviceArgs = @('device', '--port', "$Port", '--timeout', "$Timeout")
if ($DeviceId) { $deviceArgs += @('--device', $DeviceId) }
if ($Duration -gt 0) { $deviceArgs += @('--duration', "$Duration") }
if ($Command) { $deviceArgs += @('--command', $Command, '--params', $Params) }
if ($Interactive) { $deviceArgs += '--interactive' }
if ($NoReport) { $deviceArgs += '--no-report' }

$code = Invoke-Launcher $deviceArgs

Write-Host ''
switch ($code) {
    0 { Write-Host '設備通過驗收。' -ForegroundColor Green }
    1 { Write-Host '設備沒有通過，報告裡列出了必須修好的項目。' -ForegroundColor Red }
    2 { Write-Host '測試無法執行，請看上面的說明。' -ForegroundColor Yellow }
    3 { Write-Host '測試沒跑完，無法判定。' -ForegroundColor Yellow }
    default { Write-Host "結束碼 $code" -ForegroundColor Yellow }
}

exit $code
