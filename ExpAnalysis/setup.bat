@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo   ExpAnalysis - 安裝相依套件
echo   ================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo   找不到 .venv，正在建立虛擬環境...
  python -m venv .venv
  if errorlevel 1 (
    echo.
    echo   [錯誤] 無法建立虛擬環境。請確認已安裝 Python 3.10 以上並加入 PATH。
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo   [錯誤] 安裝失敗。若機台無法連外，請改用離線 wheel 安裝。
  pause
  exit /b 1
)
echo.
echo   安裝完成。執行 run.bat 啟動。
echo.
pause
