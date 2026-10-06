@echo off
rem One-time setup: a private Python environment in .venv with Ghostline's packages.
rem start.bat runs this for you the first time, so you normally never need to open it.
cd /d "%~dp0"
set PY=python
where py >nul 2>&1 && set PY=py -3
%PY% -c "import sys; sys.exit(sys.version_info < (3, 11))" >nul 2>&1
if errorlevel 1 goto nopython
if not exist .venv\Scripts\python.exe (
  echo Creating a private Python environment in .venv ...
  %PY% -m venv .venv || goto failed
)
echo Installing packages. This takes a couple of minutes, once.
.venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt || goto failed
if not exist data mkdir data
copy /y requirements.txt .venv\installed-requirements.txt >nul
echo Setup done.
if /i not "%1"=="--quiet" pause
exit /b 0

:nopython
echo.
echo Ghostline needs Python 3.11 or newer, and it isn't installed.
where winget >nul 2>&1 || goto manual
choice /m "Install Python 3.12 now (free, from python.org through winget)"
if errorlevel 2 goto manual
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements || goto manual
echo.
echo Python is installed. Close this window and double-click start.bat again.
pause
exit /b 1

:manual
echo Get it from https://www.python.org/downloads/ and tick "Add python.exe to PATH" in the installer.
echo Then double-click start.bat again.
pause
exit /b 1

:failed
echo.
echo Setup failed. Check your internet connection and try again. If it keeps failing, open an issue on
echo GitHub with the text above.
pause
exit /b 1
