@echo off
rem Migration SQLite -> PostgreSQL : simulation, confirmation, transfert, verification.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0migrate_to_postgresql_windows.ps1" %*
exit /b %errorlevel%
