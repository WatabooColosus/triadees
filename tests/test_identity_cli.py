from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_identity_verify_cli(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "triade_digimon.py",
            "identity",
            "--db",
            str(tmp_path / "identity.db"),
            "verify",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["identity"] == "Triade Omega"
    assert payload["identity_version"] == "1.0.0"
    assert payload["integrity"] == "verified"
