@echo off
setlocal
cd /d "%~dp0"
py -c "import pygame" >nul 2>&1
if errorlevel 1 (
  echo Installing pygame...
  py -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Could not install pygame automatically.
    echo Run: py -m pip install pygame
    pause
    exit /b 1
  )
)
py kill_zone.py
if errorlevel 1 pause
