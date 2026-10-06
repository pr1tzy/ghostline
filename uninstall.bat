@echo off
rem Removes Ghostline's in-game app from Assetto Corsa and the autostart entry.
rem Your laps stay in the data folder. To remove everything, delete this whole folder afterwards.
cd /d "%~dp0"
call "%~dp0stop.bat" >nul 2>&1
call "%~dp0autostart.bat" off >nul 2>&1
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "from backend import ingest; print('In-game app:', ingest.uninstall_app())"
) else (
  echo Run start.bat once before uninstalling, or delete "assettocorsa\apps\python\RaceLogger" yourself.
)
echo Ghostline is uninstalled. You can delete this folder now.
pause
