@echo off
cd /d "%~dp0"
if not exist ".venv-win\Scripts\pythonw.exe" (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1"
  if errorlevel 1 (
    pause
    exit /b 1
  )
)
start "" ".venv-win\Scripts\pythonw.exe" "%~dp0app.py"
