@echo off
setlocal

echo ===============================================
echo RefChecker Web UI - vLLM Startup Script
echo ===============================================
echo.

REM ------------------------------------------------
REM Local vLLM configuration
REM ------------------------------------------------
REM RefChecker appends /v1 internally, so keep this
REM as the server root (for example http://127.0.0.1:8001).
if "%REFCHECKER_VLLM_SERVER_URL%"=="" set "REFCHECKER_VLLM_SERVER_URL=http://127.0.0.1:1234"
if "%REFCHECKER_LLM_PROVIDER%"=="" set "REFCHECKER_LLM_PROVIDER=vllm"

REM An explicit server URL tells RefChecker not to auto-start vLLM.
set "REFCHECKER_VLLM_AUTO_START=false"

echo LLM provider: %REFCHECKER_LLM_PROVIDER%
echo vLLM server:  %REFCHECKER_VLLM_SERVER_URL%
echo vLLM API:     %REFCHECKER_VLLM_SERVER_URL%/v1
echo.

REM Optional reachability check. Do not abort RefChecker if vLLM is offline;
REM this allows you to start vLLM separately before running a check.
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Uri '%REFCHECKER_VLLM_SERVER_URL%/v1/models' -TimeoutSec 2 | Out-Null; exit 0 } catch { exit 1 }" >nul 2>&1
if errorlevel 1 (
    echo WARNING: vLLM is not responding at %REFCHECKER_VLLM_SERVER_URL%/v1/models
    echo Start your vLLM OpenAI-compatible server on port 8001, or set:
    echo   set REFCHECKER_VLLM_SERVER_URL=http://HOST:PORT
    echo.
) else (
    echo vLLM server detected.
    echo.
)

REM No ANTHROPIC_API_KEY is required when using local vLLM extraction.

echo Starting Backend Server...
echo.
start "RefChecker Backend" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

echo Waiting for backend to start...
timeout /t 5 /nobreak > nul

echo.
echo Starting Frontend Server...
echo.
start "RefChecker Frontend" cmd /k "cd web-ui && npm run dev"

echo.
echo ===============================================
echo Both servers starting...
echo.
echo Backend:  http://localhost:8000
echo Frontend: http://localhost:5173
echo vLLM:     %REFCHECKER_VLLM_SERVER_URL%/v1
echo.
echo Open http://localhost:5173 in your browser
echo For LAN access, use http://YOUR-LAN-IP:5173
echo.
echo In RefChecker Settings, select vLLM for reference extraction
echo and choose the model name served by your vLLM instance.
echo ===============================================
echo.
echo Press any key to stop the RefChecker servers...
pause > nul

taskkill /FI "WindowTitle eq RefChecker Backend*" /T /F > nul 2>&1
taskkill /FI "WindowTitle eq RefChecker Frontend*" /T /F > nul 2>&1

echo.
echo RefChecker servers stopped.
echo Note: this script does not stop your separately managed vLLM server.
pause

endlocal
