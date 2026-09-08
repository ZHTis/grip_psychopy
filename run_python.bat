@echo off
setlocal
pushd "%~dp0"
if defined GRIP_PYTHON (
    "%GRIP_PYTHON%" %*
) else if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" %*
) else (
    python %*
)
set "GRIP_EXIT_CODE=%ERRORLEVEL%"
popd
exit /b %GRIP_EXIT_CODE%
