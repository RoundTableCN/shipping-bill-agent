@echo off
setlocal EnableExtensions
cd /d "%~dp0"

rem Keep UTF-8 output when chcp is available.
if exist "%SystemRoot%\System32\chcp.com" "%SystemRoot%\System32\chcp.com" 65001 >nul

set "PY="

rem 1) Project virtualenv, if present.
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -c "import streamlit" >nul 2>nul
  if not errorlevel 1 set "PY=%~dp0.venv\Scripts\python.exe"
)
if exist "%~dp0venv\Scripts\python.exe" (
  if not defined PY (
    "%~dp0venv\Scripts\python.exe" -c "import streamlit" >nul 2>nul
    if not errorlevel 1 set "PY=%~dp0venv\Scripts\python.exe"
  )
)

rem 2) The python on PATH, only if it actually has streamlit.
if not defined PY (
  python -c "import streamlit" >nul 2>nul
  if not errorlevel 1 set "PY=python"
)

rem 3) Common per-user / machine Python installations.
if not defined PY call :try_path "%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PY call :try_path "%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PY call :try_path "%LocalAppData%\Programs\Python\Python310\python.exe"
if not defined PY call :try_path "%ProgramFiles%\Python312\python.exe"
if not defined PY call :try_path "%ProgramFiles%\Python311\python.exe"
if not defined PY call :try_path "%ProgramFiles%\Python310\python.exe"

if not defined PY (
  echo.
  echo No Python with Streamlit was found.
  echo Install dependencies with:
  echo   python -m pip install -r requirements.txt
  echo Then run this file again.
  pause
  exit /b 1
)

"%PY%" "%~dp0scripts\launch_streamlit.py" %*
set "CODE=%ERRORLEVEL%"

if not "%CODE%"=="0" (
  echo.
  echo Failed to start. Check out\launcher\streamlit.log
  pause
)
exit /b %CODE%

:try_path
if defined PY exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import streamlit" >nul 2>nul
if not errorlevel 1 set "PY=%~1"
exit /b 0
