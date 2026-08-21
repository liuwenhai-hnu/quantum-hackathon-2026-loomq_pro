@echo off
setlocal
cd /d "%~dp0"

if not defined LOOMQ_PORT set "LOOMQ_PORT=4173"
set "LOOMQ_URL=http://127.0.0.1:%LOOMQ_PORT%/"
set "LOOMQ_PYTHON_EXE="
set "LOOMQ_PYTHON_ARGS="
set "LOOMQ_SERVICE_ALREADY_RUNNING=0"

call :service_ready
if not errorlevel 1 (
  set "LOOMQ_SERVICE_ALREADY_RUNNING=1"
  goto open_browser
)

if defined VIRTUAL_ENV (
  python -c "import sys; assert sys.version_info[:2] == (3, 10)" >nul 2>&1
  if not errorlevel 1 set "LOOMQ_PYTHON_EXE=python"
)

if not defined LOOMQ_PYTHON_EXE if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; assert sys.version_info[:2] == (3, 10)" >nul 2>&1
  if not errorlevel 1 set "LOOMQ_PYTHON_EXE=%CD%\.venv\Scripts\python.exe"
)

if not defined LOOMQ_PYTHON_EXE (
  py -3.10 -c "import sys; assert sys.version_info[:2] == (3, 10)" >nul 2>&1
  if not errorlevel 1 (
    set "LOOMQ_PYTHON_EXE=py"
    set "LOOMQ_PYTHON_ARGS=-3.10"
  )
)

if not defined LOOMQ_PYTHON_EXE (
  python -c "import sys; assert sys.version_info[:2] == (3, 10)" >nul 2>&1
  if not errorlevel 1 set "LOOMQ_PYTHON_EXE=python"
)

if not defined LOOMQ_PYTHON_EXE (
  echo [LoomQ] Python 3.10 was not found.
  echo Install Python 3.10, create a virtual environment, and try again.
  pause
  exit /b 1
)

"%LOOMQ_PYTHON_EXE%" %LOOMQ_PYTHON_ARGS% -c "import sys; sys.path.insert(0, r'starter_kit'); import adapter" >nul 2>&1
if errorlevel 1 (
  echo [LoomQ] Python dependencies are missing from the selected environment.
  echo Run: python -m pip install -r starter_kit\requirements.txt
  pause
  exit /b 1
)

echo [LoomQ] Starting Product Service with %LOOMQ_PYTHON_EXE% %LOOMQ_PYTHON_ARGS% ...
start "LoomQ Product Service" cmd /k ""%LOOMQ_PYTHON_EXE%" %LOOMQ_PYTHON_ARGS% -B product_service.py --port %LOOMQ_PORT%"

set /a LOOMQ_ATTEMPT=0
:wait_for_service
call :service_ready
if not errorlevel 1 goto open_browser
set /a LOOMQ_ATTEMPT+=1
if %LOOMQ_ATTEMPT% GEQ 30 goto start_failed
timeout /t 1 /nobreak >nul
goto wait_for_service

:open_browser
if "%LOOMQ_SERVICE_ALREADY_RUNNING%"=="1" echo [LoomQ] Product Service is already running.
echo [LoomQ] Ready: %LOOMQ_URL%
if defined LOOMQ_NO_BROWSER (
  echo [LoomQ] Browser opening skipped for this test run.
) else (
  start "" "%LOOMQ_URL%"
  echo [LoomQ] Browser opened. The service runs in the Product Service window.
)
timeout /t 3 /nobreak >nul
exit /b 0

:start_failed
echo [LoomQ] Product Service did not become ready within 30 seconds.
echo Check the Product Service window for the detailed error.
pause
exit /b 1

:service_ready
powershell -NoProfile -NonInteractive -Command "$ProgressPreference = 'SilentlyContinue'; try { $response = Invoke-WebRequest -UseBasicParsing -Uri '%LOOMQ_URL%' -TimeoutSec 1; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%
