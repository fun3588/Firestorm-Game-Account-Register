@echo off
setlocal
title Firestorm WoW 自动注册 - 图形界面
cd /d "%~dp0"

REM ================= 寻找带 tkinter 的解释器 =================
set "PY="
if defined LOCALAPPDATA if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"& goto :check
if defined LOCALAPPDATA if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"& goto :check
if defined LOCALAPPDATA if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"& goto :check
if defined LOCALAPPDATA if exist "%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python310\pythonw.exe"& goto :check
if exist "C:\Python311\pythonw.exe" set "PY=C:\Python311\pythonw.exe"& goto :check
if exist "C:\Python312\pythonw.exe" set "PY=C:\Python312\pythonw.exe"& goto :check
if exist "C:\Python313\pythonw.exe" set "PY=C:\Python313\pythonw.exe"& goto :check
for %%I in (pythonw.exe) do if exist "%%~$PATH:I" set "PY=%%~$PATH:I"& goto :check
for %%I in (python.exe) do if exist "%%~$PATH:I" set "PY=%%~$PATH:I"& goto :check

echo [x] 未找到 Python 解释器。
echo [提示] 请安装 Python 3.10 或更高版本。
pause
exit /b 1

:check
"%PY:pythonw.exe=python.exe%" -c "import tkinter, tkinter.ttk" >nul 2>&1
if not errorlevel 1 goto :run

echo [x] 当前 Python 缺少 tkinter 组件。
echo [提示] 请在安装 Python 时勾选 tcl/tk and IDLE。
pause
exit /b 1

:run
start "" "%PY%" "%~dp0firestorm_gui.py"
exit /b 0
