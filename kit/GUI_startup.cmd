@echo off
rem civswitch-kit control panel launcher (uses system Python via py launcher)
where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3 "%~dp0kit-gui.py"
) else (
    start "" py -3 "%~dp0kit-gui.py"
)
