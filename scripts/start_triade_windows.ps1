$ErrorActionPreference = "Stop"
$logPath = Join-Path (Split-Path -Parent $PSScriptRoot) "artifacts\system-start.log"
try { "[$(Get-Date -Format o)] start" | Out-File -FilePath $logPath -Append -Encoding utf8 } catch {}
$pythonPath = $null
if ($args.Count -gt 1 -and $args[0] -eq '-PythonPath') { $pythonPath = $args[1] }
$repo = Split-Path -Parent $PSScriptRoot
$pythonCandidates = @(
    $pythonPath,
    (Join-Path $repo 'tools\python\python.exe'),
    (Join-Path $repo '.venv\Scripts\python.exe'),
    'C:\Users\SantiWataboo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe',
    (Get-Command python.exe -ErrorAction SilentlyContinue).Source,
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) -and $_ -notmatch '\\WindowsApps\\python(?:3)?\.exe$' }
if (-not $pythonCandidates) { throw 'No se encontró un intérprete Python utilizable para Tríade.' }
$python = [string]($pythonCandidates | Select-Object -First 1)
$python = (Resolve-Path -LiteralPath $python).Path
$env:PYTHONPATH = $repo
$env:TRIADE_RUNTIME_SCOPE = "local"
$env:TRIADE_DB_PATH = "triade/memory/triade.db"
$env:TRIADE_AUTH_DB_PATH = "triade/memory/triade.db"
$env:TRIADE_DISABLE_BACKGROUND = "0"
$env:TRIADE_POST_RUN_LEARNING = "1"
$env:TRIADE_NEURAL_LEARNING_ROUTING = "1"
# Esta máquina tiene 7.2 GB de RAM; un drenaje secuencial mantiene vivo el
# aprendizaje en segundo plano sin lanzar tres tareas pesadas a la vez.
$env:TRIADE_WORKER_CONCURRENCY = "1"
$env:TRIADE_PUBLIC_GUARDED = "true"
$env:TRIADE_LOCAL_NO_AUTH = "1"
$env:TRIADE_DATA_ANCHOR_EMAIL = "agenciadigitalwataboo@gmail.com"
$env:TRIADE_LOW_RESOURCE_MODEL = "qwen2.5:1.5b"
$env:TRIADE_LOW_RESOURCE_MODE = "1"
$env:TRIADE_SLOW_FULL_LOCAL = "1"
# La cabina realiza sondeos autenticados de varias vistas. Este límite evita
# que la reconexión de la interfaz produzca una tormenta 429, manteniendo el
# guardado de sesión y los controles de autorización intactos.
$env:TRIADE_RATE_LIMIT_PER_MINUTE = "300"
$localAppData = $env:LOCALAPPDATA
if (-not $localAppData) { $localAppData = Join-Path $env:USERPROFILE "AppData\Local" }
$env:TRIADE_BACKUP_KEY_FILE = Join-Path $localAppData "Triade\backup.key"
if (Test-Path $env:TRIADE_BACKUP_KEY_FILE) {
    $env:TRIADE_BACKUP_KEY = (Get-Content -Raw $env:TRIADE_BACKUP_KEY_FILE).Trim()
    $env:TRIADE_AUTH_VAULT_KEY = $env:TRIADE_BACKUP_KEY
}
Set-Location $repo
$worker = Join-Path $repo "scripts\triade_service_worker.ps1"
# Mantener esta tarea viva une el proceso de la tarea con el supervisor. Un
# Start-Process desacoplado hacía que Windows registrara éxito aunque la API
# quedara huérfana, impidiendo verificar Always-On.
try {
    & powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File $worker -PythonPath $python *>> $logPath
    $code = $LASTEXITCODE
    "[$(Get-Date -Format o)] exit=$code python=$python" | Out-File -FilePath $logPath -Append -Encoding utf8
    exit $code
} catch {
    "[$(Get-Date -Format o)] error=$($_.Exception.Message) python=$python" | Out-File -FilePath $logPath -Append -Encoding utf8
    exit 1
}
