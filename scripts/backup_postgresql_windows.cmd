@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0backup_postgresql_windows.ps1" %*
exit /b %errorlevel%
