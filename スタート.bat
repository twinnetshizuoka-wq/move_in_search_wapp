@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title 入居発見ツール
echo.
echo 入居発見ツールを起動しています...
echo.

call "%~dp0scripts\ensure_env.bat"
if errorlevel 1 (
  echo.
  pause
  exit /b 1
)

set "VENV_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
  echo [エラー] 実行環境が見つかりません。
  pause
  exit /b 1
)

echo アプリを開きます...
"%VENV_PY%" "%~dp0app.py"
if errorlevel 1 (
  echo.
  echo アプリの起動中にエラーが発生しました。
  pause
  exit /b 1
)

exit /b 0
