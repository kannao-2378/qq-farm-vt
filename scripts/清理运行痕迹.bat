@echo off
setlocal
cd /d "%~dp0\.."

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0clean_runtime_artifacts.py"
  goto :end
)
python "%~dp0clean_runtime_artifacts.py"

:end
pause
