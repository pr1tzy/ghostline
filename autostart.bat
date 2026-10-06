@echo off
rem Start Ghostline hidden every time you log in to Windows. Run "autostart.bat off" to remove.
set LNK=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Ghostline.lnk
if /i "%1"=="off" (del "%LNK%" >nul 2>&1 & echo Autostart removed. & exit /b)
powershell -NoProfile -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK); $s.TargetPath='wscript.exe'; $s.Arguments='\"%~dp0ghostline.vbs\"'; $s.WorkingDirectory='%~dp0'; $s.Save()"
echo Ghostline will start hidden when you log in.
