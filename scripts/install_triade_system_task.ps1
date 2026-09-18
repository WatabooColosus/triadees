#requires -RunAsAdministrator
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $repo "scripts\start_triade_windows.ps1"
$taskName = "TriadeOmegaSystem"
$taskCommand = "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`""

schtasks.exe /Create /TN $taskName /SC ONSTART /RU SYSTEM /RL LIMITED /TR $taskCommand /F | Out-Host
if (Get-ScheduledTask -TaskName "TriadeOmega" -ErrorAction SilentlyContinue) {
    Disable-ScheduledTask -TaskName "TriadeOmega" | Out-Null
    Write-Host "Disabled the old interactive TriadeOmega task."
}
Write-Host "Installed $taskName as a SYSTEM startup task."
Write-Host "Verify with: schtasks /Query /TN $taskName /V /FO LIST"
