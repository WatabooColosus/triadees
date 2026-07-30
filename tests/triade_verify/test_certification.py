from __future__ import annotations

import json
import subprocess
from pathlib import Path

from triade.verification.certification import GATES, TriadeVerifier


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "artifacts" / "triade_verify").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "verify@example.invalid"], cwd=root, check=True
    )
    subprocess.run(["git", "config", "user.name", "Verifier"], cwd=root, check=True)
    (root / "anchor").write_text("evidence", encoding="utf-8")
    subprocess.run(["git", "add", "anchor"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "anchor"], cwd=root, check=True)
    return root


def test_missing_evidence_never_becomes_verified(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    output = TriadeVerifier(root).generate(tmp_path / "result")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["result"] == "PARTIAL_SAFE"
    assert not any(manifest[gate.manifest_field] for gate in GATES)
    assert manifest["long_run_verified"] is False
    assert manifest["ci_verified"] is False


def test_only_literal_passed_true_opens_evidence_gate(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    for gate in GATES:
        path = root / "artifacts" / "triade_verify" / gate.relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"passed": true}\n', encoding="utf-8")
    output = TriadeVerifier(root).generate(tmp_path / "result")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert all(manifest[gate.manifest_field] for gate in GATES)
    assert manifest["result"] == "PARTIAL_SAFE"
    assert len(manifest["evidence_files"]) == len(GATES)
