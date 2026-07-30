#!/usr/bin/env python3
"""Evidencia runtime de autenticación, RBAC, rate limit y revocación."""

import json
import tempfile
from pathlib import Path

from triade.security.public_auth import PublicAuthStore


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        auth = PublicAuthStore(Path(directory) / "auth.db", rate_limit_per_minute=1)
        auth.create_user("auditor", "runtime-password-123", "viewer", "tenant-runtime")
        login = auth.authenticate("auditor", "runtime-password-123")
        principal = auth.authorize(login["access_token"])
        rate_blocked = False
        try:
            auth.authorize(login["access_token"])
        except RuntimeError:
            rate_blocked = True
        revoked = auth.revoke(login["access_token"], actor=principal["user_id"])
        revocation_enforced = False
        try:
            auth.authorize(login["access_token"])
        except PermissionError:
            revocation_enforced = True
        report = {
            "phase": 15,
            "principal": principal,
            "rate_blocked": rate_blocked,
            "revoked": revoked,
            "revocation_enforced": revocation_enforced,
            "passed": all((rate_blocked, revoked, revocation_enforced)),
        }
    output = Path("artifacts/triade_verify/phase_15/public_security.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
