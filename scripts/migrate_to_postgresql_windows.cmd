@echo off
rem Bascule definitive SQLite -> PostgreSQL : sauvegarde, simulation, confirmation, transfert, verification, activation.
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0migrate_to_postgresql_windows.ps1" %*
exit /b %errorlevel%
