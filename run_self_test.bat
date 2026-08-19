@echo off
cd /d "%~dp0"
call validate.bat
if errorlevel 1 (
  echo.
  echo Validation failed.
  pause
  exit /b 1
)
echo.
echo All Kill Zone validation passed.
pause
