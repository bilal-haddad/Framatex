@echo off
rem Read-only diagnostic: no migration, seed, password or database creation.
setlocal
set "FRAMATEX_DIAG_PY=%~dp0..\.venv\Scripts\python.exe"
if not exist "%FRAMATEX_DIAG_PY%" (
  echo Python .venv Windows absent. Aucune base modifiee.
  exit /b 1
)
"%FRAMATEX_DIAG_PY%" "%~dp0windows_runtime.py" diagnose
exit /b %errorlevel%
