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
$python = "C:\Users\sven6\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$env:PYTHONPATH = $repo
$env:TRIADE_RUNTIME_SCOPE = "local"
$env:TRIADE_DISABLE_BACKGROUND = "0"
$env:TRIADE_POST_RUN_LEARNING = "1"
$env:TRIADE_WORKER_CONCURRENCY = "0"
$env:TRIADE_PUBLIC_GUARDED = "true"
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
$keyCandidates += @(
    (Join-Path $env:LOCALAPPDATA "Triade\backup.key"),
    "C:\Users\sven6\AppData\Local\Triade\backup.key"
)
$env:TRIADE_BACKUP_KEY_FILE = $keyCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($env:TRIADE_BACKUP_KEY_FILE) {
    $env:TRIADE_BACKUP_KEY = (Get-Content -Raw $env:TRIADE_BACKUP_KEY_FILE).Trim()
    $env:TRIADE_AUTH_VAULT_KEY = $env:TRIADE_BACKUP_KEY
}
Set-Location $repo
$logDir = Join-Path $repo "artifacts\service_logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdout = Join-Path $logDir "triade-uvicorn.stdout.log"
$stderr = Join-Path $logDir "triade-uvicorn.stderr.log"
try { while ($true) {
    $proc = Start-Process -FilePath $python -ArgumentList @(
        "-m", "scripts.serve_local_api", "--host", "0.0.0.0", "--port", "8010"
    ) -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $proc.WaitForExit()
    Start-Sleep -Seconds 5
} } finally { $supervisorGuard.Dispose() }
