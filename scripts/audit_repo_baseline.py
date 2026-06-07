from __future__ import annotations

import argparse
import json
import py_compile
import subprocess
import sys
from pathlib import Path
from typing import Any


CORE_TESTS = [
    "tests/test_neuron_governance_cycle.py",
    "tests/test_experimental_neuron_runtime.py",
    "tests/test_stable_promotion_readiness.py",
    "tests/test_promote_neuron_stable.py",
]


REQUIRED_FILES = [
    "README.md",
    "docs/neuron_lifecycle.md",
    "triade/core/runner.py",
    "triade/core/primary_neuron_pipeline.py",
    "triade/core/experimental_neuron_runtime.py",
    "triade/core/experimental_neuron_evidence.py",
    "triade/core/stable_promotion_readiness.py",
    "triade/core/neuron_registry.py",
    "scripts/decide_primary_neuron.py",
    "scripts/promote_neuron_stable.py",
    "scripts/audit_experimental_neuron_evidence.py",
    "scripts/audit_stable_promotion_readiness.py",
    "triade/memory/schemas.sql",
]


def py_compile_audit(roots: list[str]) -> dict[str, Any]:
    errors: list[dict[str, str]] = []

    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            errors.append({"path": root, "error": "missing_root"})
            continue

        for path in root_path.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            try:
                py_compile.compile(str(path), doraise=True)
            except Exception as exc:
                errors.append({"path": str(path), "error": str(exc)})

    return {
        "ok": len(errors) == 0,
        "files_with_errors": len(errors),
        "errors": errors,
    }


def run_pytest(test_files: list[str]) -> dict[str, Any]:
    existing = [path for path in test_files if Path(path).exists()]
    missing = [path for path in test_files if not Path(path).exists()]

    if not existing:
        return {
            "ok": False,
            "returncode": None,
            "missing": missing,
            "stdout_tail": "",
            "stderr_tail": "No test files found.",
        }

    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *existing, "-q"],
        capture_output=True,
        text=True,
        check=False,
    )

    return {
        "ok": proc.returncode == 0 and not missing,
        "returncode": proc.returncode,
        "missing": missing,
        "stdout_tail": proc.stdout[-4000:],
        "stderr_tail": proc.stderr[-4000:],
    }


def required_files_audit(files: list[str]) -> dict[str, Any]:
    missing = [path for path in files if not Path(path).exists()]
    return {
        "ok": len(missing) == 0,
        "missing": missing,
    }


def runtime_artifacts_audit() -> dict[str, Any]:
    checks = {
        "db_exists": Path("triade/memory/triade.db").exists(),
        "schema_exists": Path("triade/memory/schemas.sql").exists(),
        "runs_dir_exists": Path("runs").exists(),
        "triade_runs_dir_exists": Path("triade/runs").exists(),
        "neuron_lifecycle_doc_exists": Path("docs/neuron_lifecycle.md").exists(),
    }
    return {
        "ok": all(checks.values()),
        "checks": checks,
    }


def import_runtime_reports() -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": True,
        "experimental_evidence": None,
        "stable_readiness": None,
        "errors": [],
    }

    try:
        from triade.core.experimental_neuron_evidence import build_experimental_evidence_ledger

        ledger = build_experimental_evidence_ledger(runs_dir="runs", limit=100)
        result["experimental_evidence"] = ledger.get("summary")
    except Exception as exc:
        result["ok"] = False
        result["errors"].append({"experimental_evidence": str(exc)})

    try:
        from triade.core.stable_promotion_readiness import evaluate_stable_readiness

        readiness = evaluate_stable_readiness(runs_dir="runs", limit=100)
        result["stable_readiness"] = readiness.get("summary")
    except Exception as exc:
        result["ok"] = False
        result["errors"].append({"stable_readiness": str(exc)})

    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoría baseline del repositorio Tríade Ω.")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    syntax = py_compile_audit(["triade", "apps", "scripts", "tests"])
    files = required_files_audit(REQUIRED_FILES)
    artifacts = runtime_artifacts_audit()
    runtime_reports = import_runtime_reports()
    tests = {"ok": True, "skipped": True} if args.skip_tests else run_pytest(CORE_TESTS)

    ok = all([
        syntax.get("ok"),
        files.get("ok"),
        artifacts.get("ok"),
        runtime_reports.get("ok"),
        tests.get("ok"),
    ])

    report = {
        "status": "ok" if ok else "warning",
        "mode": "repo_baseline_audit",
        "syntax": syntax,
        "required_files": files,
        "runtime_artifacts": artifacts,
        "runtime_reports": runtime_reports,
        "tests": tests,
        "summary": {
            "syntax_ok": syntax.get("ok"),
            "required_files_ok": files.get("ok"),
            "runtime_artifacts_ok": artifacts.get("ok"),
            "runtime_reports_ok": runtime_reports.get("ok"),
            "tests_ok": tests.get("ok"),
            "baseline_ok": ok,
        },
        "policy": "baseline_audit_only_no_repo_modification",
    }

    out = Path("triade/runs/repo_baseline_audit.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("=== TRIADE REPO BASELINE AUDIT ===")
        print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
        print(f"written: {out}")
        if not ok:
            print("\n--- DETAILS ---")
            print(json.dumps(report, ensure_ascii=False, indent=2))

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
