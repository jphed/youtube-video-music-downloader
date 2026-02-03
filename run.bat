@echo off
setlocal
set APPDIR=%~dp0

REM Prefer the project's venv Python if present
set PYEXE="%APPDIR%\.venv\Scripts\python.exe"
if not exist %PYEXE% set PYEXE=python

pushd "%APPDIR%"
%PYEXE% main.py
if errorlevel 1 (
  echo.
  echo The app exited with an error. Press any key to close...
  pause >nul
)
popd
endlocal
