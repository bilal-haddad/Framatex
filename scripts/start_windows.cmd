@echo off
rem FRAMATEX - demarrage local sous Windows.
rem Une commande : start_windows.cmd -Demo. Ctrl+C = arret volontaire.
rem Diagnostic sans modification de DB : diagnose_windows.cmd
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_windows.ps1" %*
exit /b %errorlevel%
