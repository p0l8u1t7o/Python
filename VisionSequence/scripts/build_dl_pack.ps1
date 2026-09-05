<#
.SYNOPSIS
    Build the deep-learning add-on pack: torch + ultralytics + onnxruntime-gpu wheels and the preloaded weights, installable offline.

.DESCRIPTION
    Vendor side. Produces build\release\VisionSequence-DL-<variant>-<ver>.zip containing
      wheels\                 every wheel for Python 3.12 / win_amd64 (torch, torchvision from the PyTorch index; the rest from PyPI)
      requirements-dl.lock.txt  the exact versions that were resolved (vsctl dl install uses it with --no-index)
      weights\                yolo11n.pt, yolo11n-seg.pt, yolo11n-cls.pt, sam2.1_t.pt, mobile_sam.pt (+ SHA256SUMS.txt)
      dl-pack.json            variant, python, torch, onnxruntime, weights
    A station installs it with: vsctl dl install VisionSequence-DL-cu128-<ver>.zip -Predict

.EXAMPLE
    .\scripts\build_dl_pack.ps1 -Cuda cu128      # RTX 30/40/50 (sm_120 needs cu128+)
    .\scripts\build_dl_pack.ps1 -Cpu             # no NVIDIA GPU
#>
[CmdletBinding()]
param(
    [string]$Cuda = '',
    [switch]$Cpu,
    [string]$Version = '',
    [string]$OutDir = '',
    [string]$PythonVersion = '3.12',
    [string[]]$Weights = @('yolo11n.pt', 'yolo11n-seg.pt', 'yolo11n-cls.pt', 'sam2.1_t.pt', 'mobile_sam.pt'),
    [string]$YoloRelease = 'v8.3.0',
    [switch]$SkipWeights
)

$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
. (Join-Path $PSScriptRoot 'vslib.ps1')
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')
Set-Location $root
if (-not $Cuda -and -not $Cpu) { $Cuda = 'cu128' }
if ($Cpu) { $variant = 'cpu' } else { $variant = $Cuda }
if (-not $Version) {
    $m = [regex]::Match((Get-Content -LiteralPath (Join-Path $root 'apps\vision\__init__.py') -Raw), '__version__\s*=\s*"([^"]+)"')
    $Version = $m.Groups[1].Value
}
if (-not $OutDir) { $OutDir = Join-Path $root 'build\release' }
$cache = Join-Path $root "build\cache\dl-$variant"
$work = Join-Path $root "build\dl-pack-$variant"
$zip = Join-Path $OutDir "VisionSequence-DL-$variant-$Version.zip"
$devPython = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $devPython)) { $devPython = 'py' }
$pyMinor = ($PythonVersion -split '\.')[0..1] -join '.'
$pyTag = ($PythonVersion -split '\.')[0..1] -join ''
New-Item -ItemType Directory -Force -Path $cache, $OutDir | Out-Null
if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
New-Item -ItemType Directory -Force -Path (Join-Path $work 'wheels'), (Join-Path $work 'weights') | Out-Null
$started = Get-Date

function Step([string]$Text) { Write-Host ("`n==> " + $Text) -ForegroundColor Cyan }

# ---- 1. torch / torchvision（PyTorch index；順序與 index 是 DL 踩坑第一條） ---------------------------------
Step "torch/torchvision wheels ($variant) -> $cache"
$common = @('-m', 'pip', 'download', '--disable-pip-version-check', '-d', $cache, '--platform', 'win_amd64', '--python-version', $pyMinor, '--implementation', 'cp', '--only-binary=:all:')
$torchIndex = "https://download.pytorch.org/whl/$variant"
& $devPython @common '--index-url' $torchIndex 'torch' 'torchvision'
if ($LASTEXITCODE) { throw "pip download torch failed" }
$torchWheel = Get-ChildItem -LiteralPath $cache -Filter "torch-*cp$pyTag*win_amd64.whl" | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $torchWheel) { throw "No torch wheel in $cache" }
$torchVer = ($torchWheel.Name -split '-')[1]

# ---- 2. 其餘（PyPI；requirements-dl.txt 不鎖 torch，這裡把解析結果凍結成 lock） -------------------------------
Step "requirements-dl.txt wheels (PyPI)"
& $devPython @common '--find-links' $cache '-r' (Join-Path $root 'requirements-dl.txt')
if ($LASTEXITCODE) { throw "pip download requirements-dl failed" }
Copy-Item -Path (Join-Path $cache '*.whl') -Destination (Join-Path $work 'wheels')
# 同名互蓋：包裡不能有 CPU 版 onnxruntime
Get-ChildItem -LiteralPath (Join-Path $work 'wheels') -Filter 'onnxruntime-1*.whl' | Remove-Item -Force
$ortWheel = Get-ChildItem -LiteralPath (Join-Path $work 'wheels') -Filter 'onnxruntime_gpu-*.whl' | Select-Object -First 1
$ortVer = ''
if ($ortWheel) { $ortVer = ($ortWheel.Name -split '-')[1] }
$lock = @("# Frozen by scripts\build_dl_pack.ps1 for $variant / Python $pyMinor on $(Get-Date -Format 'yyyy-MM-dd'); installed with --no-index by vsctl dl install.")
foreach ($w in Get-ChildItem -LiteralPath (Join-Path $work 'wheels') -Filter '*.whl' | Sort-Object Name) {
    $parts = $w.BaseName -split '-'
    $name = $parts[0].Replace('_', '-')
    if ($name -in @('torch', 'torchvision')) { continue }
    $lock += "$name==$($parts[1])"
}
[IO.File]::WriteAllText((Join-Path $work 'requirements-dl.lock.txt'), (($lock -join "`n") + "`n"))
Write-VsOk "$((Get-ChildItem -LiteralPath (Join-Path $work 'wheels')).Count) wheels, torch $torchVer, onnxruntime-gpu $ortVer"

# ---- 3. 權重（與 yolo_runtime.resolve_model／sam.py 同一個來源） -------------------------------------------------
if (-not $SkipWeights) {
    Step "Weights"
    $sums = @()
    foreach ($w in $Weights) {
        $dest = Join-Path $cache $w
        if (-not (Test-Path -LiteralPath $dest)) {
            $url = "https://github.com/ultralytics/assets/releases/download/$YoloRelease/$w"
            Write-Host "  downloading $url"
            Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $dest
        }
        Copy-Item -LiteralPath $dest -Destination (Join-Path $work 'weights')
        $sums += "{0}  {1}" -f (Get-FileHash -LiteralPath $dest -Algorithm SHA256).Hash.ToLower(), $w
    }
    [IO.File]::WriteAllText((Join-Path $work 'weights\SHA256SUMS.txt'), (($sums -join "`n") + "`n"))
    Write-VsOk "$($Weights.Count) weight files"
}

# ---- 4. 描述檔與 zip ------------------------------------------------------------------------------------------
$meta = @{ product = 'VisionSequence-DL'; version = $Version; variant = $variant; python = $pyMinor; torch = $torchVer; onnxruntime = $ortVer
           weights = @($Weights); built_at = (Get-Date).ToString('s'); install = 'vsctl dl install <this zip> [-Predict]' } | ConvertTo-Json
[IO.File]::WriteAllText((Join-Path $work 'dl-pack.json'), $meta + "`n", (New-Object Text.UTF8Encoding $false))
$readme = @(
    "VisionSequence deep-learning add-on ($variant) for VisionSequence $Version, Python $pyMinor",
    "Install on the station (elevated PowerShell): C:\VisionSequence\vsctl.cmd dl install $(Split-Path -Leaf $zip) -Predict",
    "Contents: wheels\ (torch $torchVer, ultralytics, onnxruntime-gpu $ortVer ...), weights\ (YOLO11n, SAM2), requirements-dl.lock.txt, dl-pack.json",
    "cu128 needs an NVIDIA driver that supports CUDA 12.8 (RTX 50 series needs it; older GPUs work too). Use the cpu pack without an NVIDIA GPU.",
    "The pack is kept in packs\ and reinstalled automatically by vsctl update."
) -join "`r`n"
[IO.File]::WriteAllText((Join-Path $work 'README.txt'), $readme + "`r`n")
Step "Zip"
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($work, $zip, [IO.Compression.CompressionLevel]::Fastest, $false)
Remove-Item -LiteralPath $work -Recurse -Force
$hash = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLower()
Add-Content -LiteralPath (Join-Path $OutDir 'SHA256SUMS.txt') -Value "$hash  $(Split-Path -Leaf $zip)"
Write-Host ""
Write-Host "DL pack built in $([int]((Get-Date) - $started).TotalMinutes) min: $zip ($([math]::Round((Get-Item -LiteralPath $zip).Length / 1MB)) MB)" -ForegroundColor Green
Write-Host "  $hash"
