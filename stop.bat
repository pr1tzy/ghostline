@echo off
set PIDFILE=%~dp0data\ghostline.pid
if not exist "%PIDFILE%" (echo Ghostline is not running. & exit /b)
set /p PID=<"%PIDFILE%"
taskkill /PID %PID% /T /F >nul 2>&1
del "%PIDFILE%" >nul 2>&1
echo Ghostline stopped.
