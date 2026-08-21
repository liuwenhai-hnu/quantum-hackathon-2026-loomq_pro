@echo off
setlocal
cd /d "%~dp0"

if not defined LOOMQ_PORT set "LOOMQ_PORT=4173"
set "LOOMQ_URL=http://127.0.0.1:%LOOMQ_PORT%/"
set "LOOMQ_PYTHON_EXE="
set "LOOMQ_PYTHON_ARGS="
set "LOOMQ_PYTHON_LABEL="
set "LOOMQ_SERVICE_ALREADY_RUNNING=0"

call :service_http_ready
if not errorlevel 1 (
  call :service_runtime_ready
  if not errorlevel 1 (
    set "LOOMQ_SERVICE_ALREADY_RUNNING=1"
    goto open_browser
  )
  echo [LoomQ] Port %LOOMQ_PORT% already has a Product Service without a complete backend runtime.
  echo [LoomQ] Close that service, then run start_playground.bat again from a complete Python 3.10 environment.
  pause
  exit /b 1
)

if exist ".venv\Scripts\python.exe" call :try_python "%CD%\.venv\Scripts\python.exe" "" "repository .venv"
if not defined LOOMQ_PYTHON_EXE if defined VIRTUAL_ENV if exist "%VIRTUAL_ENV%\Scripts\python.exe" call :try_python "%VIRTUAL_ENV%\Scripts\python.exe" "" "active virtual environment"
if not defined LOOMQ_PYTHON_EXE call :try_python "py" "-3.10" "Python launcher 3.10"
if not defined LOOMQ_PYTHON_EXE call :try_python "python" "" "PATH Python"

if not defined LOOMQ_PYTHON_EXE (
  echo [LoomQ] No complete Python 3.10 runtime was found.
  echo [LoomQ] Required imports: adapter, spinqit, pyqpanda, braket.
  echo [LoomQ] Prepare a repository-local environment with:
  echo   py -3.10 -m venv .venv
  echo   .venv\Scripts\python.exe -m pip install -r starter_kit\requirements.txt
  echo   start_playground.bat
  pause
  exit /b 1
)

echo [LoomQ] Runtime ready: %LOOMQ_PYTHON_LABEL%
echo [LoomQ] Starting Product Service with %LOOMQ_PYTHON_EXE% %LOOMQ_PYTHON_ARGS% ...
start "LoomQ Product Service" cmd /k ""%LOOMQ_PYTHON_EXE%" %LOOMQ_PYTHON_ARGS% -B product_service.py --port %LOOMQ_PORT%"

set /a LOOMQ_ATTEMPT=0
:wait_for_service
call :service_runtime_ready
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

:service_http_ready
powershell -NoProfile -NonInteractive -Command "$ProgressPreference = 'SilentlyContinue'; try { $response = Invoke-WebRequest -UseBasicParsing -Uri '%LOOMQ_URL%' -TimeoutSec 1; if ($response.StatusCode -eq 200) { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%

:service_runtime_ready
powershell -NoProfile -NonInteractive -Command "$ProgressPreference = 'SilentlyContinue'; try { $response = Invoke-RestMethod -Uri '%LOOMQ_URL%api/runtime-readiness' -TimeoutSec 2; if ($response.ready -eq $true) { exit 0 } } catch {}; exit 1" >nul 2>&1
exit /b %errorlevel%

:try_python
set "LOOMQ_CANDIDATE_EXE=%~1"
set "LOOMQ_CANDIDATE_ARGS=%~2"
set "LOOMQ_CANDIDATE_LABEL=%~3"
"%LOOMQ_CANDIDATE_EXE%" %LOOMQ_CANDIDATE_ARGS% -c "import sys; assert sys.version_info[:2] == (3, 10); sys.path.insert(0, r'starter_kit'); import adapter, spinqit, pyqpanda, braket; from braket.devices import LocalSimulator" >nul 2>&1
if errorlevel 1 (
  echo [LoomQ] Skipping %LOOMQ_CANDIDATE_LABEL%: Python 3.10 or runtime dependencies are incomplete.
  exit /b 0
)
set "LOOMQ_PYTHON_EXE=%LOOMQ_CANDIDATE_EXE%"
set "LOOMQ_PYTHON_ARGS=%LOOMQ_CANDIDATE_ARGS%"
set "LOOMQ_PYTHON_LABEL=%LOOMQ_CANDIDATE_LABEL%"
exit /b 0
