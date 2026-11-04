@echo off
setlocal
rem Job Agent: start the local API (port 8765) and the dashboard (port 3000),
rem then open the browser. Close the two server windows to stop everything.
rem Usage: double-click, or run "start.bat --no-browser".

cd /d "%~dp0"
title Job Agent launcher

where python >nul 2>nul || (echo [ERROR] Python not found. Install Python and add it to PATH. & goto :fail)
where npm >nul 2>nul || (echo [ERROR] npm not found. Install Node.js. & goto :fail)

if not exist "frontend\node_modules" (
    echo First run: installing frontend packages, this can take a few minutes...
    call npm --prefix frontend install || (echo [ERROR] npm install failed. & goto :fail)
)

curl -s -o nul http://127.0.0.1:8765/api/health
if errorlevel 1 (
    echo Starting local API on http://127.0.0.1:8765 ...
    start "Job Agent API (close to stop)" cmd /k python api_local.py
) else (
    echo Local API is already running.
)

curl -s -o nul http://localhost:3000
if errorlevel 1 (
    echo Starting dashboard on http://localhost:3000 ...
    start "Job Agent Dashboard (close to stop)" cmd /k "cd /d frontend && npm run dev"
) else (
    echo Dashboard is already running.
)

echo Waiting for the dashboard...
set /a tries=0
:wait
curl -s -o nul http://localhost:3000 && goto :ready
set /a tries+=1
if %tries% geq 90 (echo [ERROR] Dashboard did not start within 90 seconds. Check its window. & goto :fail)
ping -n 2 127.0.0.1 >nul
goto :wait

:ready
echo Job Agent is running: http://localhost:3000
if /i not "%~1"=="--no-browser" start "" http://localhost:3000
endlocal
exit /b 0

:fail
echo.
pause
endlocal
exit /b 1
