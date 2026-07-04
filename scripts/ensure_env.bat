@echo off
setlocal EnableExtensions EnableDelayedExpansion

cd /d "%~dp0.."
set "ROOT=%CD%"
set "VENV_DIR=%ROOT%\.venv"
set "VENV_PY=%VENV_DIR%\Scripts\python.exe"
set "MARKER=%VENV_DIR%\.setup_complete"
set "REQ=%ROOT%\requirements.txt"

echo.
echo ========================================
echo  入居発見ツール - 環境チェック
echo ========================================
echo.

if exist "%VENV_PY%" if exist "%MARKER%" (
  echo セットアップ済みです。起動を続けます...
  exit /b 0
)

echo 初回起動のため、必要なソフトを自動で用意します。
echo インターネット接続が必要です。数分かかることがあります。
echo.

set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=py -3"
)

if not defined PY_CMD (
  where python >nul 2>&1
  if not errorlevel 1 (
    python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_CMD=python"
  )
)

if not defined PY_CMD (
  echo [エラー] Python が見つかりませんでした。
  echo.
  echo このツールを使うには Python 3.10 以上が必要です。
  echo 次のページからインストールしてください。
  echo.
  echo   https://www.python.org/downloads/windows/
  echo.
  echo 【重要】インストール画面で
  echo   「Add python.exe to PATH」
  echo に必ずチェックを入れてください。
  echo.
  echo インストール後、このウィンドウを閉じて
  echo もう一度「スタート.bat」をダブルクリックしてください。
  echo.
  start "" "https://www.python.org/downloads/windows/"
  exit /b 1
)

echo Python を確認しました。
echo.

if not exist "%VENV_PY%" (
  echo 専用の実行環境を作成しています...
  %PY_CMD% -m venv "%VENV_DIR%"
  if errorlevel 1 (
    echo [エラー] 実行環境の作成に失敗しました。
    exit /b 1
  )
)

echo 必要な部品をインストールしています...
"%VENV_PY%" -m pip install --upgrade pip
if errorlevel 1 (
  echo [エラー] pip の更新に失敗しました。
  exit /b 1
)

"%VENV_PY%" -m pip install -r "%REQ%"
if errorlevel 1 (
  echo [エラー] requirements.txt のインストールに失敗しました。
  exit /b 1
)

echo ブラウザ自動操作用の部品をインストールしています...
"%VENV_PY%" -m playwright install chromium
if errorlevel 1 (
  echo [エラー] Playwright のインストールに失敗しました。
  exit /b 1
)

echo setup-ok>"%MARKER%"
echo.
echo セットアップが完了しました。
echo.
exit /b 0
