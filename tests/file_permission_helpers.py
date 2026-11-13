"""Permission fixtures use the platform's real security authority."""

import os

from triade.security.file_privacy import (
    _windows_acl,
    inspect_private_file,
    protect_private_file,
)


def set_file_mode(path, mode):
    if os.name != "nt":
        path.chmod(mode)
    elif mode == 0o600:
        protect_private_file(path)
    else:
        _windows_acl(
            "$acl=Get-Acl -LiteralPath $env:TRIADE_PRIVACY_PATH; "
            "$sid=New-Object System.Security.Principal.SecurityIdentifier('S-1-1-0'); "
            "$rule=New-Object System.Security.AccessControl.FileSystemAccessRule($sid,'Read','Allow'); "
            "$acl.AddAccessRule($rule); Set-Acl -LiteralPath $env:TRIADE_PRIVACY_PATH -AclObject $acl; '{}'",
            path,
        )


def assert_private(path):
    assert inspect_private_file(path)["private"]
