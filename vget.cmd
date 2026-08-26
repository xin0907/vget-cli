@echo off
setlocal
pushd "%~dp0" >nul
if errorlevel 1 exit /b 1
".venv\Scripts\vget.exe" %*
set "VGET_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %VGET_EXIT_CODE%
