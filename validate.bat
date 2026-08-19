@echo off
setlocal
cd /d "%~dp0"

set "KZ_PYTHON="
if exist ".venv\Scripts\python.exe" set "KZ_PYTHON=.venv\Scripts\python.exe"
if not defined KZ_PYTHON (
  where py >nul 2>&1
  if not errorlevel 1 set "KZ_PYTHON=py"
)
if not defined KZ_PYTHON (
  where python >nul 2>&1
  if not errorlevel 1 set "KZ_PYTHON=python"
)

if not defined KZ_PYTHON (
  echo Python 3 was not found. Install Python 3.10 or newer and try again.
  exit /b 1
)

"%KZ_PYTHON%" validate.py %*
exit /b %errorlevel%
