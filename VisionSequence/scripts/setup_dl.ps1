# 安裝深度學習可選依賴（torch cu128 + ultralytics + onnxruntime-gpu），最後用 manage.py dl_check 驗證。
#   .\scripts\setup_dl.ps1              預設 CUDA 12.8 wheel（RTX 50 系列必須 cu128 以上）
#   .\scripts\setup_dl.ps1 -Cuda cu126  其他 CUDA 版本
#   .\scripts\setup_dl.ps1 -Cpu         沒有 NVIDIA GPU：裝 CPU 版 torch 與 CPU 版 onnxruntime
# 順序很重要：先 torch（pytorch index）→ 再 requirements-dl.txt（PyPI）；否則 ultralytics 會拉 CPU 版 torch。
param(
    [string]$Cuda = "cu128",
    [switch]$Cpu
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { Write-Host "找不到 .venv，請先執行 .\scripts\dev.ps1 -Setup" -ForegroundColor Red; exit 1 }

Write-Host "== 1/4 torch / torchvision" -ForegroundColor Cyan
if ($Cpu) {
    & $py -m pip install --upgrade torch torchvision --index-url https://download.pytorch.org/whl/cpu
} else {
    & $py -m pip install --upgrade torch torchvision --index-url "https://download.pytorch.org/whl/$Cuda"
}

Write-Host "== 2/4 移除 CPU 版 onnxruntime（與 onnxruntime-gpu 同名衝突）" -ForegroundColor Cyan
& $py -m pip uninstall -y onnxruntime 2>$null | Out-Null

Write-Host "== 3/4 ultralytics / onnx / onnxslim / onnxruntime" -ForegroundColor Cyan
if ($Cpu) {
    & $py -m pip install --upgrade "ultralytics>=8.3.0" "onnx>=1.16" "onnxslim>=0.1.34" "onnxruntime>=1.20" "nvidia-ml-py>=12"
} else {
    & $py -m pip install --upgrade -r requirements-dl.txt
}

Write-Host "== 4/4 驗證" -ForegroundColor Cyan
$env:PYTHONIOENCODING = "utf-8"
& $py manage.py dl_check
