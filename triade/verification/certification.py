"""Evidence-driven TRIADE-VERIFY-v1 manifest generation."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class EvidenceGate:
    manifest_field: str
    relative_path: str


GATES = (
    EvidenceGate("identity_verified", "phase_03/identity_continuity.json"),
    EvidenceGate("triadic_causality_verified", "phase_04/triadic_causality.json"),
    EvidenceGate("memory_continuity_verified", "phase_05/memory_longitudinal.json"),
    EvidenceGate("execution_truth_verified", "phase_01/execution_truth.json"),
    EvidenceGate("autonomous_learning_verified", "phase_09/autonomous_learning.json"),
    EvidenceGate("rollback_verified", "phase_16/recovery.json"),
    EvidenceGate("federation_verified", "phase_14/federation.json"),
)


class TriadeVerifier:
    """Build a certification bundle from previously executed evidence only."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.source = self.root / "artifacts" / "triade_verify"

    @staticmethod
    def _load_passed(path: Path) -> bool:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return False
        return value.get("passed") is True

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _git_sha(self) -> str:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    @staticmethod
    def _load_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _long_runtime_passed(value: dict[str, Any], duration: int, sha: str) -> bool:
        metrics = value.get("metrics")
        if not isinstance(metrics, dict):
            return False
        return (
            value.get("passed") is True
            and value.get("sha") == sha
            and value.get("wall_clock_not_compressed") is True
            and float(value.get("elapsed_seconds") or 0) >= duration
            and int(value.get("requested_duration_seconds") or 0) >= duration
            and float(value.get("availability") or 0) >= 0.99
            and int(metrics.get("duplicate_effects") or 0) == 0
            and int(metrics.get("lost_tasks") or 0) == 0
            and int(metrics.get("false_completed") or 0) == 0
            and int(metrics.get("db_corruption") or 0) == 0
            and int(metrics.get("late_results_accepted") or 0) == 0
            and int(metrics.get("artifact_loss") or 0) == 0
            and float(metrics.get("rollback_success_percent") or 0) == 100.0
        )

    @staticmethod
    def _ci_passed(value: dict[str, Any], sha: str) -> bool:
        required = {
            "Runtime Truth CI",
            "Tríade Tests",
            "Measurement Core",
            "Python Tests",
        }
        workflows = value.get("workflows")
        if not isinstance(workflows, list):
            return False
        observed = {
            str(item.get("name"))
            for item in workflows
            if isinstance(item, dict) and item.get("conclusion") == "success"
        }
        return (
            value.get("passed") is True
            and value.get("sha") == sha
            and required <= observed
        )

    def generate(self, output: str | Path | None = None) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = Path(output) if output is not None else self.source / timestamp
        destination = destination.resolve()
        evidence_dir = destination / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=False)

        current_sha = self._git_sha()
        manifest: dict[str, Any] = {
            "system": "Triade Omega",
            "certification": "TRIADE-VERIFY-v1",
            "sha": current_sha,
        }
        copied: list[dict[str, str]] = []
        for gate in GATES:
            source_path = self.source / gate.relative_path
            passed = source_path.is_file() and self._load_passed(source_path)
            manifest[gate.manifest_field] = passed
            if source_path.is_file():
                target = evidence_dir / source_path.name
                shutil.copy2(source_path, target)
                copied.append({"file": target.name, "sha256": self._sha256(target)})

        runtime_24h = self.source / "phase_17" / "runtime_24h.json"
        runtime_72h = self.source / "phase_17" / "runtime_72h.json"
        chaos = self.source / "phase_17" / "chaos_short.json"
        runtime_24h_data = self._load_json(runtime_24h)
        runtime_72h_data = self._load_json(runtime_72h)
        chaos_data = self._load_json(chaos)
        long_run = (
            self._long_runtime_passed(runtime_24h_data, 86_400, current_sha)
            and self._long_runtime_passed(runtime_72h_data, 259_200, current_sha)
            and chaos_data.get("full_chaos_verified") is True
            and chaos_data.get("sha") == current_sha
        )
        manifest["long_run_verified"] = long_run
        ci_path = self.source / "phase_18" / "ci.json"
        manifest["ci_verified"] = self._ci_passed(self._load_json(ci_path), current_sha)

        for source_path in (runtime_24h, runtime_72h, chaos, ci_path):
            if source_path.is_file():
                target = evidence_dir / source_path.name
                shutil.copy2(source_path, target)
                copied.append({"file": target.name, "sha256": self._sha256(target)})

        mandatory = [key for key in manifest if key.endswith("_verified")]
        all_verified = all(manifest[key] is True for key in mandatory)
        manifest["result"] = "VERIFIED_FEDERATED" if all_verified else "PARTIAL_SAFE"
        manifest["evidence_bundle"] = "evidence"
        manifest["evidence_files"] = copied

        (destination / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        missing = [key for key in mandatory if not manifest[key]]
        lines = [
            "# TRIADE-VERIFY-v1",
            "",
            f"SHA evaluado: `{manifest['sha']}`",
            f"Resultado: `{manifest['result']}`",
            "",
            "## Dimensiones",
            "",
        ]
        lines.extend(f"- `{key}`: `{str(manifest[key]).lower()}`" for key in mandatory)
        lines.extend(["", "## Pendiente", ""])
        lines.extend(f"- `{key}`" for key in missing)
        lines.extend(
            ["", "Los hashes de la evidencia copiada constan en `manifest.json`.", ""]
        )
        (destination / "report.md").write_text("\n".join(lines), encoding="utf-8")
        return destination
