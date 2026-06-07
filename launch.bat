@echo off
cd /d "%~dp0"
title Life-Log

if not exist ".env" (
    echo [ERROR] .env file not found.
    pause
    exit /b 1
)

echo [1/2] Starting server...
if not exist "logs" mkdir logs
start "Life-Log Server" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8001 --log-level info"

timeout /t 3 /nobreak >nul

echo [2/2] Starting ngrok...
start "ngrok Tunnel" cmd /k "ngrok http 8001"

echo.
echo ============================================
echo  NEXT STEPS:
echo  1. Copy the Forwarding URL from ngrok window
echo     e.g. https://xxxx.ngrok-free.app
echo  2. Open LINE Developers
echo     https://developers.line.biz/
echo  3. Messaging API - Webhook URL
echo     https://xxxx.ngrok-free.app/webhook
echo  4. Click [Verify] - check for Success
echo ============================================
echo.
pause
