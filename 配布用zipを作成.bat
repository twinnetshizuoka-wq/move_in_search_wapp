@echo off
setlocal EnableExtensions
cd /d "%~dp0"

title 配布用zipを作成
echo.
echo 配布用 zip を作成しています...
echo.

set "PY_CMD="
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys" >nul 2>&1
  if not errorlevel 1 set "PY_CMD=py -3"
)
if not defined PY_CMD (
  where python >nul 2>&1
  if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
  echo [エラー] Python が見つかりません。
  pause
  exit /b 1
)

%PY_CMD% "%~dp0scripts\build_release_zip.py"
if errorlevel 1 (
  echo.
  echo zip の作成に失敗しました。
  pause
  exit /b 1
)

echo.
echo 完了しました。 dist フォルダを確認してください。
echo.
pause
exit /b 0
