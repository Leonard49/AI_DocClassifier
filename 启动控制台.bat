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
echo Starting AI DocClassifier Console at http://127.0.0.1:8787
echo Close this window to stop the console server.
echo.
start "" http://127.0.0.1:8787
"%PY%" run_console.py
pause
