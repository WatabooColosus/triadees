$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\sven6\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$env:PYTHONPATH = $repo
$env:TRIADE_RUNTIME_SCOPE = "local"
$env:TRIADE_DISABLE_BACKGROUND = "0"
$env:TRIADE_POST_RUN_LEARNING = "1"
# Esta máquina tiene 7.2 GB de RAM; un drenaje secuencial mantiene vivo el
# aprendizaje en segundo plano sin lanzar tres tareas pesadas a la vez.
$env:TRIADE_WORKER_CONCURRENCY = "0"
$env:TRIADE_PUBLIC_GUARDED = "true"
$env:TRIADE_BACKUP_KEY_FILE = Join-Path $env:LOCALAPPDATA "Triade\backup.key"
if (Test-Path $env:TRIADE_BACKUP_KEY_FILE) {
    $env:TRIADE_BACKUP_KEY = (Get-Content -Raw $env:TRIADE_BACKUP_KEY_FILE).Trim()
    $env:TRIADE_AUTH_VAULT_KEY = $env:TRIADE_BACKUP_KEY
}
Set-Location $repo
$logDir = Join-Path $repo "artifacts\service_logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "triade-uvicorn.log"
try {
    $previousErrorAction = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $python -m uvicorn apps.single_port_app:app --host 0.0.0.0 --port 8010 *>> $log
    $exitCode = $LASTEXITCODE
    $ErrorActionPreference = $previousErrorAction
} catch {
    $_ | Out-File -FilePath $log -Append -Encoding utf8
    $exitCode = 1
}
exit ([int]$exitCode)
