@echo off
rem FRAMATEX - demarrage PostgreSQL local sous Windows (moteur unique).
rem Options : -Demo -Port 8000 -NoBrowser -CheckOnly -Reload
rem Diagnostic sans modification de DB : diagnose_windows.cmd
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_postgresql_windows.ps1" %*
exit /b %errorlevel%
