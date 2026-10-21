@echo off
rem FRAMATEX - demarrage local sous Windows.
rem Diagnostic, nettoyage des anciens serveurs sur le port, verifications HTTP,
rem puis ouverture du navigateur. Options : -Port 8010  -Reload  -NoBrowser  -CheckOnly
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_windows.ps1" %*
exit /b %errorlevel%
