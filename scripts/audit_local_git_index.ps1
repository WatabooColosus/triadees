param()
$git = Join-Path $PSScriptRoot '..\..\..\tools\mingit\cmd\git.exe'
if (-not (Test-Path $git)) { throw "Git portable no encontrado" }
$paths = & $git diff --cached --name-only
$forbidden = $paths | Where-Object { $_ -match '(?i)(^|/)(triade/memory/backups/|.*\.(db|db-wal|db-shm|db-journal|bak|backup[^/]*)$|runs/|reports/|artifacts/|models/|ollama/|frontend/node_modules/|\.env($|\.))' }
if ($forbidden) { $forbidden; exit 2 }
& $git diff --cached --check
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Output "git_index_safe=true"
Write-Output "staged_count=$($paths.Count)"
