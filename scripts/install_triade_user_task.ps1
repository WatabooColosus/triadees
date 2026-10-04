#requires -RunAsAdministrator
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $repo 'scripts\start_triade_windows.ps1'
$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType InteractiveToken -RunLevel Limited
Register-ScheduledTask -TaskName 'TriadeOmegaSystem' -Action $action -Trigger $trigger -Principal $principal -Description 'Tríade Ω local: API, runtime y Ollama low-resource' -Force | Out-Null
Write-Host "Installed TriadeOmegaSystem for $user at logon."
