# 建立 CAD Studio / text-to-cad 需要的環境（只需執行一次）：
#   cad\.venv        Python 3.12 + cadgen（build123d / OCP 核心，約 1 GB）
#   cad\text-to-cad  earthtojake/text-to-cad skill（gen / export / inspect / snapshot 工具，釘 tag）
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

# skill 要跟上面的 cadgen 同版：0.5.0 起上游把 skills\cad\scripts\* 全換成 cadgen CLI，
# 抓 main 會讓 CAD Studio 找不到 gen / export / inspect / snapshot。改 cadgen 版本時這裡要一起改。
$skillTag = '0.4.28'
$skill = Join-Path $root 'cad\text-to-cad'
$skillProbe = Join-Path $skill 'skills\cad\scripts\export'
if (-not (Test-Path $skill)) {
    Write-Host "[3/3] 下載 text-to-cad skill ($skillTag)..." -ForegroundColor Cyan
    git clone --depth 1 --branch $skillTag https://github.com/earthtojake/text-to-cad $skill
} elseif (-not (Test-Path $skillProbe)) {
    Write-Host "[3/3] text-to-cad skill 版本不符（缺 skills\cad\scripts），切到 $skillTag..." -ForegroundColor Cyan
    git -C $skill fetch --depth 1 origin tag $skillTag
    git -C $skill checkout $skillTag
} else {
    Write-Host '[3/3] text-to-cad skill 已存在' -ForegroundColor DarkGray
}
if (-not (Test-Path $skillProbe)) { throw "text-to-cad skill 不完整：找不到 $skillProbe" }

$env:PYTHONUTF8 = '1'
& $py -c "import cadgen, build123d; print('cadgen OK, build123d', build123d.__version__)"
Write-Host ''
Write-Host '完成。之後用 .\start.ps1 啟動即可使用 CAD Studio。' -ForegroundColor Green
Write-Host 'AI 產碼模式另需 Claude 憑證：$env:ANTHROPIC_API_KEY = "sk-ant-..."（設定後重新 start）。'
