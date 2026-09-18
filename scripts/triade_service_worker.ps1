$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$python = "C:\Users\sven6\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$env:PYTHONPATH = $repo
$env:TRIADE_RUNTIME_SCOPE = "local"
$env:TRIADE_DISABLE_BACKGROUND = "0"
$env:TRIADE_POST_RUN_LEARNING = "1"
$env:TRIADE_WORKER_CONCURRENCY = "0"
$env:TRIADE_PUBLIC_GUARDED = "true"
$keyCandidates = @(
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
while ($true) {
    $proc = Start-Process -FilePath $python -ArgumentList @(
        "-m", "uvicorn", "apps.single_port_app:app", "--host", "0.0.0.0", "--port", "8010"
    ) -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $proc.WaitForExit()
    Start-Sleep -Seconds 5
}
