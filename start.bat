@echo off
rem Starts Ghostline with a console window (close the window to stop it). The first run sets everything up.
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First start: setting up Ghostline.
  call "%~dp0setup.bat" --quiet || exit /b 1
) else (
  fc /b requirements.txt .venv\installed-requirements.txt >nul 2>&1 || (
    echo Ghostline was updated: installing the new packages.
    call "%~dp0stop.bat" >nul 2>&1
    call "%~dp0setup.bat" --quiet || exit /b 1
  )
)
.venv\Scripts\python.exe run.py %*
if errorlevel 1 pause
