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

    def generate(self, output: str | Path | None = None) -> Path:
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        destination = Path(output) if output is not None else self.source / timestamp
        destination = destination.resolve()
        evidence_dir = destination / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=False)

        manifest: dict[str, Any] = {
            "system": "Triade Omega",
            "certification": "TRIADE-VERIFY-v1",
            "sha": self._git_sha(),
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

        runtime = self.source / "phase_17" / "runtime_short.json"
        chaos = self.source / "phase_17" / "chaos_short.json"
        long_run = False
        if runtime.is_file() and chaos.is_file():
            runtime_data = json.loads(runtime.read_text(encoding="utf-8"))
            chaos_data = json.loads(chaos.read_text(encoding="utf-8"))
            long_run = (
                runtime_data.get("requested_duration_seconds", 0) >= 259_200
                and chaos_data.get("full_chaos_verified") is True
            )
        manifest["long_run_verified"] = long_run
        manifest["ci_verified"] = False

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
