"""Run the complete suite and derive evidence from pytest's JUnit output."""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    directory = ROOT / "reports/level8"
    directory.mkdir(parents=True, exist_ok=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    sources = sorted((ROOT / "tests").rglob("*.py"))
    digest = hashlib.sha256()
    for path in sources:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    command = [sys.executable, "-m", "pytest", "-o", "faulthandler_timeout=90", "--junitxml=reports/level8/full_suite.xml"]
    start = time.monotonic()
    timestamp = datetime.now(UTC).isoformat()
    with (directory / "full_suite.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env={**os.environ, "PYTHONUTF8": "1"}, check=False)
    xml_path = directory / "full_suite.xml"
    cases = ET.parse(xml_path).getroot().findall(".//testcase") if xml_path.exists() else []
    failed = [c for c in cases if c.find("failure") is not None or c.find("error") is not None]
    skipped = [{"test": c.get("classname", "") + "::" + c.get("name", ""), "reason": c.find("skipped").get("message", "")} for c in cases if c.find("skipped") is not None]
    report = {
        "timestamp": timestamp, "git_sha": sha, "python_version": sys.version, "platform": platform.platform(),
        "tests_collected": len(cases), "passed": len(cases) - len(failed) - len(skipped), "failed": len(failed), "skipped": len(skipped),
        "duration_seconds": round(time.monotonic() - start, 3), "commands": [command], "exit_codes": [result.returncode],
        "suite_hash": digest.hexdigest(), "junit_sha256": hashlib.sha256(xml_path.read_bytes()).hexdigest() if xml_path.exists() else None,
        "skip_reasons": skipped, "skips_justified": not skipped,
        "truth": result.returncode == 0 and bool(cases) and not failed,
        "failures": [{"test": c.get("classname", "") + "::" + c.get("name", ""), "message": (c.find("failure") if c.find("failure") is not None else c.find("error")).get("message", "")} for c in failed],
    }
    (directory / "test_evidence.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (directory / "test_evidence.md").write_text(f"# Full pytest evidence\n\nRevision: `{sha}`\n\nCollected {len(cases)}, passed {report['passed']}, failed {len(failed)}, skipped {len(skipped)}.\n\nExit: {result.returncode}. Duration: {report['duration_seconds']} seconds.\n\nCommand: `{' '.join(command)}`\n\nSuite SHA256: `{report['suite_hash']}`\n\nSee `test_evidence.json` for each failure and skip. Skips require individual review before certification.\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("tests_collected", "passed", "failed", "skipped", "duration_seconds", "truth")}))
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
