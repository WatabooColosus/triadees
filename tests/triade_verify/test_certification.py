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


def test_ci_requires_same_sha_and_all_required_workflows(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    path = root / "runs/triade_verify_live/phase_18/ci.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "sha": sha,
                "passed": True,
                "workflows": [
                    {"name": name, "conclusion": "success"}
                    for name in (
                        "Runtime Truth CI",
                        "Tríade Tests",
                        "Measurement Core",
                        "Python Tests",
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    output = TriadeVerifier(root).generate(tmp_path / "result")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["ci_verified"] is True

    path.write_text(path.read_text().replace(sha, "wrong-sha"), encoding="utf-8")
    second = TriadeVerifier(root).generate(tmp_path / "second")
    second_manifest = json.loads((second / "manifest.json").read_text(encoding="utf-8"))
    assert second_manifest["ci_verified"] is False


def test_long_run_requires_both_real_windows_metrics_and_full_chaos(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    phase = root / "runs/triade_verify_live/phase_17"
    phase.mkdir(parents=True)
    metrics = {
        "duplicate_effects": 0,
        "lost_tasks": 0,
        "false_completed": 0,
        "db_corruption": 0,
        "late_results_accepted": 0,
        "artifact_loss": 0,
        "rollback_success_percent": 100.0,
    }
    for name, duration in (("runtime_24h.json", 86_400), ("runtime_72h.json", 259_200)):
        (phase / name).write_text(
            json.dumps(
                {
                    "passed": True,
                    "sha": subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=root,
                        check=True,
                        capture_output=True,
                        text=True,
                    ).stdout.strip(),
                    "wall_clock_not_compressed": True,
                    "elapsed_seconds": duration,
                    "requested_duration_seconds": duration,
                    "availability": 0.99,
                    "metrics": metrics,
                }
            ),
            encoding="utf-8",
        )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (phase / "chaos.json").write_text(
        json.dumps({"full_chaos_verified": True, "sha": sha}), encoding="utf-8"
    )

    output = TriadeVerifier(root).generate(tmp_path / "result")
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["long_run_verified"] is True
