@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set PY=.venv\Scripts\python.exe
) else (
  set PY=python
)

echo Installing console deps if needed...
"%PY%" -m pip install -q fastapi "uvicorn[standard]" pydantic
echo.

REM 释放旧控制台占用的 8787，避免浏览器仍连到旧进程
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8787" ^| findstr "LISTENING"') do (
  echo Stopping old console PID %%p on port 8787...
  taskkill /F /PID %%p >nul 2>&1
)

echo Starting AI DocClassifier Console at http://127.0.0.1:8787
echo Branch tip: look for filter chip 「归纳新标题」. If missing, Ctrl+F5 hard refresh.
echo Close this window to stop the console server.
echo.
timeout /t 1 /nobreak >nul
start "" http://127.0.0.1:8787
"%PY%" run_console.py
pause
