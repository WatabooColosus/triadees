"""Exportación reproducible de evidencia del Regression Gate."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from triade.evaluation import EvaluationRun
from triade.regression.gate import MetricPolicy, RegressionReport


class RegressionArtifactExporter:
    """Escribe artefactos JSON y un manifiesto con hashes SHA-256."""

    def __init__(self, root: str | Path = "artifacts/regression") -> None:
        self.root = Path(root)

    @staticmethod
    def _write_json(path: Path, payload: Any) -> str:
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        path.write_bytes(encoded + b"\n")
        return hashlib.sha256(encoded + b"\n").hexdigest()

    def export(
        self,
        *,
        report: RegressionReport,
        policies: Iterable[MetricPolicy],
        baseline: EvaluationRun,
        candidate: EvaluationRun,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if report.baseline_evaluation_id != baseline.evaluation_id:
            raise ValueError("baseline no coincide con el reporte")
        if report.candidate_evaluation_id != candidate.evaluation_id:
            raise ValueError("candidate no coincide con el reporte")
        if report.suite_id != candidate.suite_id or report.suite_version != candidate.suite_version:
            raise ValueError("suite del reporte inconsistente")

        destination = self.root / report.report_id
        files = {
            "report.json": report.to_dict(),
            "policies.json": [policy.to_dict() for policy in policies],
            "baseline.json": baseline.to_dict(),
            "candidate.json": candidate.to_dict(),
            "metadata.json": dict(metadata or {}),
        }
        hashes: dict[str, str] = {}
        for filename, payload in files.items():
            hashes[filename] = self._write_json(destination / filename, payload)

        manifest = {
            "artifact_version": "1.0.0",
            "report_id": report.report_id,
            "candidate_id": report.candidate_id,
            "capability": report.capability,
            "decision": report.decision,
            "suite_id": report.suite_id,
            "suite_version": report.suite_version,
            "files": hashes,
        }
        manifest_hash = self._write_json(destination / "manifest.json", manifest)
        return {
            "directory": str(destination),
            "manifest": str(destination / "manifest.json"),
            "manifest_sha256": manifest_hash,
            **manifest,
        }
