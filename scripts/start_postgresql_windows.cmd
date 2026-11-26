@echo off
rem FRAMATEX sur PostgreSQL : start_postgresql_windows.cmd [-Demo] [-Port 8000]
rem Prerequis : .env (copie de .env.example) et Docker Desktop demarre (ou PostgreSQL installe).
rem L'ancien demarrage SQLite reste disponible : start_windows.cmd
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_postgresql_windows.ps1" %*
exit /b %errorlevel%
