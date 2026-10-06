param([string]$PythonPath)
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repo "artifacts\service_logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
# OS-held lock: shared across Windows sessions, released on process exit.
# Acquire before touching the shared logs or launching an API.
try {
    $supervisorGuard = [System.IO.File]::Open(
        (Join-Path $logDir 'supervisor.lock'),
        [System.IO.FileMode]::OpenOrCreate,
        [System.IO.FileAccess]::ReadWrite,
        [System.IO.FileShare]::None
    )
} catch {
    Write-Error 'Another supervisor holds the repository lock; startup refused.'
    exit 1
}
$pythonCandidates = @(
    $PythonPath,
    (Join-Path $repo '.venv\Scripts\python.exe'),
    'C:\Users\SantiWataboo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe',
    (Get-Command python.exe -ErrorAction SilentlyContinue).Source,
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe')
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) -and $_ -notmatch '\\WindowsApps\\python(?:3)?\.exe$' }
if (-not $pythonCandidates) { Write-Error 'No se encontró Python para el supervisor.'; exit 1 }
$python = [string]($pythonCandidates | Select-Object -First 1)
$python = (Resolve-Path -LiteralPath $python).Path
$env:PYTHONPATH = $repo
$env:TRIADE_RUNTIME_SCOPE = "local"
$env:TRIADE_DB_PATH = "triade/memory/triade.db"
$env:TRIADE_AUTH_DB_PATH = "triade/memory/triade.db"
$env:TRIADE_DISABLE_BACKGROUND = "0"
$env:TRIADE_POST_RUN_LEARNING = "1"
$env:TRIADE_NEURAL_LEARNING_ROUTING = "1"
$env:TRIADE_WORKER_CONCURRENCY = "1"
$env:TRIADE_PUBLIC_GUARDED = "true"
$env:TRIADE_LOCAL_NO_AUTH = "1"
$env:TRIADE_LOW_RESOURCE_MODEL = "qwen2.5:1.5b"
$env:TRIADE_LOW_RESOURCE_MODE = "1"
$env:TRIADE_SLOW_FULL_LOCAL = "1"
$env:OLLAMA_NUM_PARALLEL = "1"
$env:OLLAMA_MAX_LOADED_MODELS = "1"
$env:OLLAMA_KEEP_ALIVE = "0"
$env:TRIADE_RATE_LIMIT_PER_MINUTE = "300"
# Read only explicitly configured search settings; never log credential values.
foreach ($searchSetting in @('TRIADE_SEARCH_PROVIDER', 'RAPIDAPI_KEY', 'BRAVE_SEARCH_API_KEY')) {
    $searchValue = [Environment]::GetEnvironmentVariable($searchSetting, 'User')
    if ($searchValue) { [Environment]::SetEnvironmentVariable($searchSetting, $searchValue, 'Process') }
}
$keyCandidates = @()
# Packaged apps can virtualize AppData paths. This contains only a physical
# file location, never key material, so SYSTEM can read the same existing key.
$keyLocationConfig = Join-Path $repo 'config\backup_key_location.json'
if (Test-Path -LiteralPath $keyLocationConfig) {
    $keyLocation = Get-Content -Raw -LiteralPath $keyLocationConfig | ConvertFrom-Json
    if ($keyLocation.key_file) { $keyCandidates += [string]$keyLocation.key_file }
}
$localAppData = $env:LOCALAPPDATA
if (-not $localAppData) { $localAppData = Join-Path $env:USERPROFILE "AppData\Local" }
$keyCandidates += @(
    (Join-Path $localAppData "Triade\backup.key"),
    "C:\Users\sven6\AppData\Local\Triade\backup.key"
)
$env:TRIADE_BACKUP_KEY_FILE = $keyCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($env:TRIADE_BACKUP_KEY_FILE) {
    $env:TRIADE_BACKUP_KEY = (Get-Content -Raw $env:TRIADE_BACKUP_KEY_FILE).Trim()
    $env:TRIADE_AUTH_VAULT_KEY = $env:TRIADE_BACKUP_KEY
}
# Fallos consecutivos de arranque; controla el backoff del bucle.
$script:triade_restart_failures = 0
Set-Location $repo
$logDir = Join-Path $repo "artifacts\service_logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdout = Join-Path $logDir "triade-uvicorn.stdout.log"
$stderr = Join-Path $logDir "triade-uvicorn.stderr.log"
try { while ($true) {
    $proc = Start-Process -FilePath $python -ArgumentList @(
        "-m", "scripts.serve_local_api", "--host", "127.0.0.1", "--port", "8010"
    ) -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    # `High` hacía que Tríade tenga prioridad sobre el servidor de Ollama y
    # sobre el propio SO. Con 1.6 GB libres de 7.2 eso aggravate el
    # starvación: 82 ciclos `runtime_cycle_skipped_resource_cooldown` en 24h
    # por "RAM disponible muy baja". `Normal` devuelve la precedencia justa.
    try { $proc.PriorityClass = 'Normal' } catch { }
    $proc.WaitForExit()
    # Sin freno, un fallo que se repite puede gastar la CPU reiniciando en
    # bucle. El backoff crece hasta un minuto y se reinicia si el proceso
    # llego a vivir un rato.
    if ($proc.ExitCode -ne 0) {
        $restartDelay = [Math]::Min(60, 5 * [Math]::Pow(2, [Math]::Min(3, $script:triade_restart_failures)))
        $script:triade_restart_failures = [int]$script:triade_restart_failures + 1
        Write-Error "Tríade terminó con código $($proc.ExitCode); reintentando en ${restartDelay}s."
        Start-Sleep -Seconds $restartDelay
    } else {
        $script:triade_restart_failures = 0
        Start-Sleep -Seconds 5
    }
} } finally { $supervisorGuard.Dispose() }
