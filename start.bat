@echo off
rem Starts Ghostline with a console window (close the window to stop it). The first run sets everything up.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First start: setting up Ghostline.
  call "%~dp0setup.bat" --quiet || exit /b 1
)
.venv\Scripts\python.exe run.py %*
if errorlevel 1 pause
