@echo off
call "%~dp0run_python.bat" "%~dp0data_viewer/view_multichannel.py" %*
if errorlevel 1 pause
