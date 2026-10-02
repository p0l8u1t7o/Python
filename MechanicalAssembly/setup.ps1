# 一鍵建置開發環境：Node 依賴（npm）＋ Python 虛擬環境（.venv）
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

& npm.cmd install
if ($LASTEXITCODE) { throw 'npm install 失敗' }

# cadquery-ocp 8.0.1 只有 Python 3.12 的 wheel
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & py.exe -3.12 -m venv .venv
    if ($LASTEXITCODE) { throw '建立 .venv 失敗，請確認已安裝 Python 3.12（py -0 可列出版本）' }
}
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt
if ($LASTEXITCODE) { throw 'pip install 失敗' }

Write-Host '環境就緒：npm.cmd run dev 啟動工作台，npm.cmd test／npm.cmd run test:native 執行測試。'
