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
# La cabina realiza sondeos autenticados de varias vistas. Este límite evita
# que la reconexión de la interfaz produzca una tormenta 429, manteniendo el
# guardado de sesión y los controles de autorización intactos.
$env:TRIADE_RATE_LIMIT_PER_MINUTE = "300"
$env:TRIADE_BACKUP_KEY_FILE = Join-Path $env:LOCALAPPDATA "Triade\backup.key"
if (Test-Path $env:TRIADE_BACKUP_KEY_FILE) {
    $env:TRIADE_BACKUP_KEY = (Get-Content -Raw $env:TRIADE_BACKUP_KEY_FILE).Trim()
    $env:TRIADE_AUTH_VAULT_KEY = $env:TRIADE_BACKUP_KEY
}
Set-Location $repo
$worker = Join-Path $repo "scripts\triade_service_worker.ps1"
# Mantener esta tarea viva une el proceso de la tarea con el supervisor. Un
# Start-Process desacoplado hacía que Windows registrara éxito aunque la API
# quedara huérfana, impidiendo verificar Always-On.
& powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $worker
exit $LASTEXITCODE
