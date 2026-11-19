@echo off
setlocal
where py.exe >nul 2>&1
if errorlevel 1 goto use_python
py.exe -3 -B -u "%~dp0tools\cmtfa\build_windows.py" %*
goto finish
:use_python
python.exe -B -u "%~dp0tools\cmtfa\build_windows.py" %*
:finish
set "build_result=%errorlevel%"
if "%~1"=="" pause
exit /b %build_result%
