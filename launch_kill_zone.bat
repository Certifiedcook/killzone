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
  echo Python 3 was not found.
  echo Install Python 3.10 or newer from https://www.python.org/downloads/
  pause
  exit /b 1
)

"%KZ_PYTHON%" -c "import pygame" >nul 2>&1
if errorlevel 1 (
  echo Installing pygame...
  "%KZ_PYTHON%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Could not install pygame automatically.
    echo Run: "%KZ_PYTHON%" -m pip install -r requirements.txt
    pause
    exit /b 1
  )
)
"%KZ_PYTHON%" kill_zone.py
if errorlevel 1 pause
