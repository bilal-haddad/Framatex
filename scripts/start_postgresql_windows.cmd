@echo off
rem Alias explicite du demarrage PostgreSQL. La commande habituelle start_windows.cmd fait de meme.
rem Options : -Demo -Port 8000 -NoBrowser -CheckOnly -Reload
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_postgresql_windows.ps1" %*
exit /b %errorlevel%
