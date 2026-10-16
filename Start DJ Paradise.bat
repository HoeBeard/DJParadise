@echo off
REM ==========================================================
REM  DJ Paradise  -  HB Software  -  https://hbcs.info
REM  Double-click to start. Installs anything missing.
REM ==========================================================
setlocal EnableExtensions
title DJ Paradise  ^|  HB Software
cd /d "%~dp0"
set "LAUNCHER=%~dp0launcher.py"
set "PYEXE="

echo.
echo   DJ PARADISE
echo   by HB Software
echo.
echo   Checking your system...

call :find
if defined PYEXE goto launch

echo   Installing Python (one-time setup, this can take a few minutes)...
where winget >nul 2>&1
if not errorlevel 1 (
    winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements >nul 2>&1
    call :find
)
if defined PYEXE goto launch

echo   Downloading Python installer...
set "PYSETUP=%TEMP%\djp-python-setup.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol='Tls12'; Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe' -OutFile '%PYSETUP%'"
if exist "%PYSETUP%" (
    "%PYSETUP%" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1 Include_tcltk=1 Include_pip=1 Include_test=0
    del "%PYSETUP%" >nul 2>&1
    call :find
)
if defined PYEXE goto launch

echo.
echo   DJ Paradise could not set up Python automatically.
echo   Install Python 3.12 from https://www.python.org/downloads/
echo   then double-click "Start DJ Paradise" again.
echo.
pause
exit /b 1

:launch
set "PYW=%PYEXE:python.exe=pythonw.exe%"
if exist "%PYW%" (
    start "" "%PYW%" "%LAUNCHER%"
) else (
    start "" "%PYEXE%" "%LAUNCHER%"
)
exit /b 0

REM ---------------------------------------------------------
:find
for %%V in (3.13 3.12 3.11 3.10 3.14) do call :trycmd py -%%V
call :trycmd python
for %%D in (Python313 Python312 Python311 Python310 Python314) do call :trypath "%LOCALAPPDATA%\Programs\Python\%%D\python.exe"
for %%D in (Python313 Python312 Python311 Python310 Python314) do call :trypath "%ProgramFiles%\%%D\python.exe"
goto :eof

:trycmd
if defined PYEXE goto :eof
%* "%LAUNCHER%" --check >nul 2>&1
if errorlevel 1 goto :eof
for /f "usebackq delims=" %%P in (`%* "%LAUNCHER%" --where`) do set "PYEXE=%%P"
goto :eof

:trypath
if defined PYEXE goto :eof
if not exist "%~1" goto :eof
"%~1" "%LAUNCHER%" --check >nul 2>&1
if errorlevel 1 goto :eof
set "PYEXE=%~1"
goto :eof
