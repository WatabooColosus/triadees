"""Private file permissions: POSIX modes or Windows ACLs, verified after writes."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _windows_acl(script: str, path: Path) -> dict:
    powershell = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run(
            [str(powershell), "-NoProfile", "-NonInteractive", "-Command", "$ErrorActionPreference='Stop'; " + script],
            env={**os.environ, "TRIADE_PRIVACY_PATH": str(path.resolve())},
            capture_output=True, text=True, timeout=15, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PermissionError("windows_file_acl_inspection_failed") from exc
    if result.returncode:
        raise PermissionError("windows_file_acl_inspection_failed")
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        raise PermissionError("windows_file_acl_response_invalid") from exc
    if not isinstance(value, dict):
        raise PermissionError("windows_file_acl_response_invalid")
    return value


def inspect_private_file(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(path)
    if os.name != "nt":
        mode = path.stat().st_mode & 0o777
        return {"private": not mode & 0o077, "authority": "posix", "mode": f"{mode:04o}"}
    return _windows_acl(
        "$current=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value; "
        "$allowed=@($current,'S-1-5-18','S-1-5-32-544'); "
        "$acl=Get-Acl -LiteralPath $env:TRIADE_PRIVACY_PATH; "
        "$owner=$acl.GetOwner([System.Security.Principal.SecurityIdentifier]).Value; "
        "$public=@($acl.Access | Where-Object { $_.AccessControlType -eq 'Allow' -and "
        "$_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -notin $allowed }); "
        "@{private=($public.Count -eq 0 -and $owner -in $allowed); authority='windows_acl'; "
        "mode=$(if($public.Count -eq 0 -and $owner -in $allowed){'private_acl'}else{'public_acl'})} | ConvertTo-Json -Compress",
        path,
    )


def protect_private_file(path: Path) -> dict:
    if os.name != "nt":
        path.chmod(0o600)
    else:
        _windows_acl(
            "$current=[System.Security.Principal.WindowsIdentity]::GetCurrent().User; "
            "$acl=New-Object System.Security.AccessControl.FileSecurity; "
            "$acl.SetOwner($current); $acl.SetAccessRuleProtection($true,$false); "
            "foreach($sid in @($current.Value,'S-1-5-18','S-1-5-32-544') | Select-Object -Unique){ "
            "$id=New-Object System.Security.Principal.SecurityIdentifier($sid); "
            "$rule=New-Object System.Security.AccessControl.FileSystemAccessRule($id,'FullControl','Allow'); "
            "$acl.AddAccessRule($rule) }; "
            "Set-Acl -LiteralPath $env:TRIADE_PRIVACY_PATH -AclObject $acl; '{}'",
            path,
        )
    result = inspect_private_file(path)
    if not result["private"]:
        raise PermissionError("private_file_permissions_not_enforced")
    return result
