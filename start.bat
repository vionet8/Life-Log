@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Life-Log ^& Focus

echo.
echo  ============================================
echo   Life-Log ^& Focus - LINE Bot Backend
echo  ============================================
echo.

if not exist ".env" (
    echo  [!] .env ファイルが見つかりません
    echo  [!] .env.example をコピーして .env を作成し、各 API キーを設定してください
    echo.
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    set PYTHON=.venv\Scripts\python.exe
) else (
    set PYTHON=C:\Users\vione\anaconda3\python.exe
)

echo  Python: %PYTHON%
echo  起動中... http://localhost:8001/health
echo  終了するには Ctrl+C を押してください
echo.

%PYTHON% -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --reload

pause
