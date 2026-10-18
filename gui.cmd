@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0gui.ps1" %*
exit /b %errorlevel%
