# 建立 CAD Studio / text-to-cad 需要的環境（只需執行一次）：
#   cad\.venv        Python 3.12 + cadgen（build123d / OCP 核心，約 1 GB）
#   cad\text-to-cad  earthtojake/text-to-cad skill（gen / export / inspect / snapshot 工具）
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = Join-Path $root 'cad\.venv'
$py = Join-Path $venv 'Scripts\python.exe'

if (-not (Test-Path $py)) {
    Write-Host '[1/3] 建立 cad\.venv (Python 3.12)...' -ForegroundColor Cyan
    py -3.12 -m venv $venv
}
Write-Host '[2/3] 安裝 cadgen 0.4.28 + playwright（需要網路，約數分鐘）...' -ForegroundColor Cyan
& $py -m pip install --upgrade pip
& $py -m pip install cadgen==0.4.28 playwright

$skill = Join-Path $root 'cad\text-to-cad'
if (-not (Test-Path (Join-Path $skill 'skills\cad\scripts\export'))) {
    Write-Host '[3/3] 下載 text-to-cad skill...' -ForegroundColor Cyan
    git clone --depth 1 https://github.com/earthtojake/text-to-cad $skill
} else {
    Write-Host '[3/3] text-to-cad skill 已存在' -ForegroundColor DarkGray
}

$env:PYTHONUTF8 = '1'
& $py -c "import cadgen, build123d; print('cadgen OK, build123d', build123d.__version__)"
Write-Host ''
Write-Host '完成。之後用 .\start.ps1 啟動即可使用 CAD Studio。' -ForegroundColor Green
Write-Host 'AI 產碼模式另需 Claude 憑證：$env:ANTHROPIC_API_KEY = "sk-ant-..."（設定後重新 start）。'
