@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0gui_scripts\new_main_pyqt.py"
  if errorlevel 1 goto :fail
  exit /b 0
)

python "%~dp0gui_scripts\new_main_pyqt.py"
if errorlevel 1 goto :fail
exit /b 0

:fail
echo.
echo 启动失败。请在项目根目录执行: pip install -r requirements.txt
pause
exit /b 1
