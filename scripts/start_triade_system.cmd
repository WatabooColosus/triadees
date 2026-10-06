@echo off
setlocal
set "REPO=E:\triade"
set "PYTHONHOME=%REPO%\tools\python"
set "PYTHONPATH=%REPO%"
set "TRIADE_RUNTIME_SCOPE=local"
set "TRIADE_DB_PATH=triade\memory\triade.db"
set "TRIADE_AUTH_DB_PATH=triade\memory\triade.db"
set "TRIADE_DISABLE_BACKGROUND=0"
set "TRIADE_POST_RUN_LEARNING=1"
set "TRIADE_NEURAL_LEARNING_ROUTING=1"
set "TRIADE_WORKER_CONCURRENCY=1"
set "TRIADE_PUBLIC_GUARDED=true"
set "TRIADE_LOCAL_NO_AUTH=1"
set "TRIADE_LOW_RESOURCE_MODEL=qwen2.5:1.5b"
set "TRIADE_LOW_RESOURCE_MODE=1"
set "TRIADE_SLOW_FULL_LOCAL=1"
cd /d "%REPO%"
echo [%date% %time%] system launcher start>> "%REPO%\artifacts\system-start.log"
curl.exe -fsS http://127.0.0.1:8010/api/health >nul 2>&1
if %ERRORLEVEL% EQU 0 (
  echo [%date% %time%] existing healthy runtime>> "%REPO%\artifacts\system-start.log"
  exit /b 0
)
"%REPO%\tools\python\python.exe" -m scripts.serve_local_api --host 127.0.0.1 --port 8010 >> "%REPO%\artifacts\system-start.log" 2>&1
set "CODE=%ERRORLEVEL%"
echo [%date% %time%] system launcher exit=%CODE%>> "%REPO%\artifacts\system-start.log"
exit /b %CODE%
