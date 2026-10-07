"""Conservative level-8 evidence audit. Never starts or mutates the runtime."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIMENSIONS = {
    "architecture": ["cognitive_architecture"],
    "memory": ["database_integrity", "restart_persistence"],
    "runtime": ["runtime_e2e", "runtime_live", "metabolism_live"],
    "autonomy": ["background_autonomy", "bounded_autonomy"],
    "learning": ["learning_longitudinal", "education_application", "causal_production_use"],
    "recovery": ["error_recovery", "rollback_verified"],
    "concurrency": ["concurrency"],
    "resource_efficiency": ["resource_governor", "low_ram", "idle_efficiency"],
    "security": ["security_audit"],
    "observability": ["runtime_live", "workers_live", "scheduler_live"],
    "testing": ["tests", "frontend"],
    "ci": ["ci"],
    "longitudinal_evidence": ["longitudinal_runtime"],
}


def calculate(gates: dict[str, str]) -> dict:
    """Each equally weighted dimension measures its fraction of proven gates."""
    dimensions = {
        name: round(10 * sum(gates.get(g) == "PASS" for g in required) / len(required), 2)
        for name, required in DIMENSIONS.items()
    }
    score = sum(dimensions.values()) / len(dimensions)
    caps = []
    for gate, limit, reason in (
        ("tests", 7.0, "tests failed or are not demonstrated"),
        ("error_recovery", 7.5, "recovery not demonstrated"),
        ("learning_longitudinal", 7.5, "longitudinal learning not demonstrated"),
        ("runtime_e2e", 6.5, "runtime E2E not demonstrated"),
    ):
        if gates.get(gate) != "PASS":
            score = min(score, limit)
            caps.append({"maximum": limit, "reason": reason})
    if gates.get("ci") == "RED-CODE":
        score = min(score, 7.0)
        caps.append({"maximum": 7.0, "reason": "CI code failure"})
    required = sorted({g for items in DIMENSIONS.values() for g in items})
    return {
        "dimensions": dimensions,
        "score": round(score, 1),
        "caps": caps,
        "LEVEL_8_CANDIDATE": score >= 8 and all(gates.get(g) == "PASS" for g in required),
        "unproven": [g for g in required if gates.get(g) != "PASS"],
        "scale": "Engineering certification coverage; not a consciousness or AGI measure",
    }


def load_evidence(path: Path, sha: str) -> tuple[dict, dict]:
    if not path.is_file():
        return {}, {"path": str(path), "accepted": False, "reason": "missing"}
    raw = path.read_bytes()
    try:
        body = json.loads(raw)
    except (ValueError, UnicodeError):
        return {}, {"path": str(path), "accepted": False, "reason": "invalid JSON"}
    accepted = isinstance(body, dict) and body.get("git_sha") == sha and bool(body.get("timestamp"))
    ref = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "accepted": accepted}
    if not accepted:
        ref["reason"] = "missing timestamp or revision mismatch"
        return {}, ref
    return body, ref


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports/level8")
    args = parser.parse_args()
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    gates = {g: "PENDING" for items in DIMENSIONS.values() for g in items}
    refs = []
    for name, filename in (("tests", "test_evidence.json"), ("frontend", "frontend_evidence.json"), ("ci", "ci_blocker.json")):
        body, ref = load_evidence(args.report_dir / filename, sha)
        refs.append(ref)
        if not body:
            continue
        if name == "tests":
            gates[name] = "PASS" if body.get("truth") is True and body.get("failed") == 0 and body.get("passed", 0) > 0 and all(c == 0 for c in body.get("exit_codes", [1])) and body.get("skips_justified") is True else "FAIL"
        elif name == "frontend":
            gates[name] = "PASS" if body.get("exit_code") == 0 and body.get("installation_exit_code") == 0 and body.get("bundles") else "FAIL"
        else:
            gates[name] = "RED-EXTERNAL" if body.get("classification") == "PLATFORM_FAILURE" else "PENDING"
    baseline, ref = load_evidence(args.report_dir / "baseline.json", sha)
    refs.append(ref)
    database = baseline.get("database", {})
    if database.get("integrity") == ["ok"] and database.get("foreign_key_violations") == 0:
        gates["database_integrity"] = "PASS"
    # Counts in older autonomy snapshots are not imported as certification.
    # Runtime/concurrency/learning need their own revision-bound protocols.
    report = {"timestamp": datetime.now(UTC).isoformat(), "git_sha": sha, "gates": gates, "evidence": refs, **calculate(gates)}
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "final_score.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    rows = "\n".join(f"| {g} | {s} |" for g, s in sorted(gates.items()))
    (args.report_dir / "final_score.md").write_text(f"# Evidence audit\n\nRevision: `{sha}`\n\nScore: {report['score']}/10\n\nLEVEL_8_CANDIDATE: {report['LEVEL_8_CANDIDATE']}\n\nThis is certification coverage, not a claim of cognitive capability. Missing evidence earns no points.\n\n| Gate | Result |\n|---|---|\n{rows}\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["LEVEL_8_CANDIDATE"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
