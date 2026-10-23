"""Conservative level-8 evidence audit. Never starts or mutates the runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DIMENSIONS = {
    "architecture": ["cognitive_architecture"],
    "memory": ["database_integrity", "restart_persistence"],
    "runtime": ["runtime_e2e", "runtime_live", "metabolism_live"],
    "autonomy": ["background_autonomy", "bounded_autonomy"],
    "learning": [
        "learning_longitudinal",
        "education_application",
        "causal_production_use",
    ],
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
        name: round(
            10 * sum(gates.get(g) == "PASS" for g in required) / len(required), 2
        )
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
        "LEVEL_8_CANDIDATE": score >= 8
        and all(
            gates.get(g) == "PASS" or (g == "ci" and gates.get(g) == "RED-EXTERNAL")
            for g in required
        ),
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
    accepted = (
        isinstance(body, dict)
        and body.get("git_sha") == sha
        and bool(body.get("timestamp"))
    )
    if (
        not accepted
        and isinstance(body, dict)
        and body.get("timestamp")
        and re.fullmatch("[0-9a-f]{40}", str(body.get("git_sha", "")))
        and re.fullmatch("[0-9a-f]{40}", sha)
    ):
        old = body["git_sha"]
        ancestor = (
            subprocess.run(
                ["git", "merge-base", "--is-ancestor", old, sha],
                cwd=ROOT,
                capture_output=True,
                check=False,
            ).returncode
            == 0
        )
        if ancestor:
            changed = subprocess.check_output(
                ["git", "diff", "--name-only", old, sha], cwd=ROOT, text=True
            ).splitlines()
            accepted = all(p.startswith("reports/") for p in changed)
    ref = {
        "path": str(path),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "accepted": accepted,
    }
    if not accepted:
        ref["reason"] = "missing timestamp or revision mismatch"
        return {}, ref
    return body, ref


def load_protocol(path: Path, sha: str) -> tuple[dict, dict]:
    body, ref = load_evidence(path, sha)
    if body or not path.is_file():
        return body, ref
    try:
        raw = json.loads(path.read_bytes())
    except (ValueError, UnicodeError):
        return {}, ref
    if not isinstance(raw, dict):
        return {}, ref
    from scripts.run_level8_soak import runtime_hash

    if raw.get("timestamp") and raw.get("runtime_source_hash") == runtime_hash():
        ref.update(
            accepted=True,
            reason="Measured runtime code matches; delivery commits may differ",
        )
        return raw, ref
    return {}, ref


def closure_gates(report_dir: Path, sha: str):
    gates = {}
    refs = []
    for filename, kind in [
        ("learning_longitudinal_v2.json", "learning"),
        ("../evolution/learning_transfer_latest.json", "learning"),
        ("recovery_end_to_end.json", "recovery"),
        ("clean_restart_v2.json", "clean"),
        ("background_autonomy_v2.json", "soak"),
        ("resource_transition.json", "resources"),
    ]:
        body, ref = load_protocol(report_dir / filename, sha)
        refs.append(ref)
        if not body:
            continue
        if kind == "learning":
            a, b, c = (
                body.get(k, []) for k in ("baseline", "learned", "negative_control")
            )
            rate = lambda xs: (
                sum(x.get("success") is True for x in xs) / len(xs) if xs else 0
            )
            matched = bool(a) and [x.get("amount") for x in a] == [
                x.get("amount") for x in b
            ] == [x.get("amount") for x in c]
            transfer = all(x.get("amount") != body.get("training_input") for x in b)
            proven = (
                matched
                and transfer
                and rate(b) > rate(a)
                and rate(a) == rate(c)
                and all(x.get("injected_ids") for x in b)
                and all(not x.get("injected_ids") for x in c)
                and body.get("db_integrity") == "ok"
            )
            gates["learning_longitudinal"] = "PASS" if proven else "FAIL"
            # Experimental inference is never imported as productive education.
        elif kind == "clean":
            obs = body.get("observations", [])
            proven = len(obs) >= 2 and all(
                x.get("exit_code") == 0
                and x.get("integrity") == "ok"
                and x.get("db_lock_reacquired")
                and x.get("final_background_state")
                and not any(x["final_background_state"].values())
                for x in obs
            )
            # A clean process exit plus identity is not proof that learned,
            # consolidated state survives a restart.
            persisted = obs[0].get("consolidated_knowledge") if obs else None
            if (
                proven
                and persisted
                and persisted == obs[-1].get("consolidated_knowledge")
                and obs[0].get("identity")
                and obs[0]["identity"] == obs[-1].get("identity")
            ):
                gates["restart_persistence"] = "PASS"
        elif kind == "recovery":
            task = body.get("task", {})
            api = body.get("api", {})
            proven = (
                task.get("final_task_status") == "completed"
                and task.get("duplicate_effects") == 0
                and task.get("effect_result") == [["sum-recovery-47", 47]]
                and task.get("db_integrity") == "ok"
                and task.get("automatic_recovery") is True
                and task.get("lease_after", {}).get("lease_generation", 0)
                > task.get("lease_before", {}).get("lease_generation", 0)
                and api.get("automatic_recovery") is True
                and api.get("pid_before") != api.get("pid_after")
                and api.get("deep_health_status") == 200
                and api.get("workers_active") is True
                and api.get("metabolism_progress") is True
                and api.get("db_integrity") == "ok"
            )
            # These independent experiments do not correlate an in-flight
            # production task with the API crash and recovered effect.
            gates["isolated_task_and_api_recovery"] = "PASS" if proven else "PENDING"
            gates["error_recovery"] = "PENDING"
        elif kind == "resources":
            observations = body.get("observations", [])
            modes = [x.get("effective_mode") for x in observations]
            ordered = [x.get("timestamp", "") for x in observations] == sorted(
                x.get("timestamp", "") for x in observations
            )
            if (
                modes
                == ["full_local_guarded", "light_background", "full_local_guarded"]
                and ordered
                and all(
                    x.get("running") is True and x.get("can_run_workers") is True
                    for x in observations
                )
                and observations[1].get("can_nourish_neurons") is False
                and observations[2].get("can_nourish_neurons") is True
            ):
                gates["resource_governor"] = "PASS"
                gates["low_ram"] = "PASS"
        else:
            samples = body.get("observations", [])
            from scripts.run_level8_soak import summarize

            if len(samples) < 2:
                continue
            # The collector's stopwatch includes the first/last real probe.
            # A sample timestamp precedes its process/SQLite observations.
            started = datetime.fromisoformat(body["timestamp"])
            first_lag = (
                datetime.fromisoformat(samples[0]["at"]) - started
            ).total_seconds()
            measured = (
                min(
                    float(body.get("duration_seconds", 0)),
                    (
                        datetime.fromisoformat(samples[-1]["at"]) - started
                    ).total_seconds(),
                )
                if 0 <= first_lag <= 30
                else 0
            )
            result = summarize(
                samples, measured, body.get("runtime_source_unchanged") is True
            )
            if result["truth"]:
                for gate in (
                    "maintenance_autonomy",
                    "longitudinal_runtime",
                    "runtime_live",
                    "metabolism_live",
                ):
                    gates[gate] = "PASS"
                # Maintenance throughput alone is not the need -> planning ->
                # learning circuit. Its correlated validator remains pending.
                gates["background_autonomy"] = "PENDING"
                if all(
                    s.get("heartbeat", {}).get("workers_active") is True
                    for s in samples
                ):
                    gates["workers_live"] = "PASS"
    return gates, refs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", type=Path, default=ROOT / "reports/level8")
    args = parser.parse_args()
    sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    gates = {g: "PENDING" for items in DIMENSIONS.values() for g in items}
    refs = []
    for name, filename in (
        ("tests", "test_evidence.json"),
        ("frontend", "frontend_evidence.json"),
        ("ci", "ci_blocker.json"),
    ):
        body, ref = load_evidence(args.report_dir / filename, sha)
        if (
            not body
            and name in {"frontend", "ci"}
            and (args.report_dir / filename).is_file()
        ):
            try:
                prior = json.loads((args.report_dir / filename).read_bytes())
                scope = "frontend" if name == "frontend" else ".github/workflows"
                old = prior.get("git_sha", "")
                ancestor = (
                    subprocess.run(
                        ["git", "merge-base", "--is-ancestor", old, sha],
                        cwd=ROOT,
                        capture_output=True,
                        check=False,
                    ).returncode
                    == 0
                )
                unchanged = (
                    ancestor
                    and not subprocess.check_output(
                        ["git", "diff", "--name-only", old, sha, "--", scope],
                        cwd=ROOT,
                        text=True,
                    ).strip()
                )
                if unchanged:
                    body = prior
                    ref.update(
                        accepted=True,
                        reason="Source scope unchanged from measured ancestor revision",
                    )
            except (ValueError, subprocess.SubprocessError):
                pass
        refs.append(ref)
        if not body:
            continue
        if name == "tests":
            gates[name] = (
                "PASS"
                if body.get("truth") is True
                and body.get("failed") == 0
                and body.get("passed", 0) > 0
                and all(c == 0 for c in body.get("exit_codes", [1]))
                and body.get("skips_justified") is True
                else "FAIL"
            )
        elif name == "frontend":
            gates[name] = (
                "PASS"
                if body.get("exit_code") == 0
                and body.get("installation_exit_code") == 0
                and body.get("bundles")
                else "FAIL"
            )
        else:
            gates[name] = (
                "RED-EXTERNAL"
                if body.get("classification") == "PLATFORM_FAILURE"
                else "PENDING"
            )
    baseline, ref = load_evidence(args.report_dir / "baseline.json", sha)
    refs.append(ref)
    database = baseline.get("database", {})
    if (
        database.get("integrity") == ["ok"]
        and database.get("foreign_key_violations") == 0
    ):
        gates["database_integrity"] = "PASS"
    extra, extra_refs = closure_gates(args.report_dir, sha)
    gates.update(extra)
    refs.extend(extra_refs)
    tests, _ = load_evidence(args.report_dir / "test_evidence.json", sha)
    junit = args.report_dir / "full_suite.xml"
    if (
        tests.get("truth") is True
        and junit.is_file()
        and hashlib.sha256(junit.read_bytes()).hexdigest() == tests.get("junit_sha256")
    ):
        cases = list(ET.parse(junit).getroot().iter("testcase"))
        proven = lambda fragment: (
            bool([c for c in cases if fragment in c.get("classname", "")])
            and all(
                not list(c.iter("failure"))
                and not list(c.iter("error"))
                and not list(c.iter("skipped"))
                for c in cases
                if fragment in c.get("classname", "")
            )
        )
        if proven("test_chat_end_to_end_real"):
            gates["runtime_e2e"] = "PASS"
        if proven("test_runtime_concurrency_script"):
            gates["concurrency"] = "PASS"
    # Counts in older autonomy snapshots are not imported as certification.
    # Runtime/concurrency/learning need their own revision-bound protocols.
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "git_sha": sha,
        "gates": gates,
        "evidence": refs,
        **calculate(gates),
    }
    args.report_dir.mkdir(parents=True, exist_ok=True)
    (args.report_dir / "final_score.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    rows = "\n".join(f"| {g} | {s} |" for g, s in sorted(gates.items()))
    (args.report_dir / "final_score.md").write_text(
        f"# Evidence audit\n\nRevision: `{sha}`\n\nScore: {report['score']}/10\n\nLEVEL_8_CANDIDATE: {report['LEVEL_8_CANDIDATE']}\n\nThis is certification coverage, not a claim of cognitive capability. Missing evidence earns no points.\n\n| Gate | Result |\n|---|---|\n{rows}\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2))
    return 0 if report["LEVEL_8_CANDIDATE"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
