"""Measure and reject the bounded recovery experiment's inferior configuration."""
from __future__ import annotations
import hashlib
import json
import subprocess
from pathlib import Path
from uuid import uuid4
from triade.core.contracts import utc_now
from triade.evaluation import EvaluationRun, MetricResult
from triade.learning.knowledge_probe import build_transfer_probe
from triade.regression.gate import RegressionGate, MetricPolicy
from triade.regression.rollback import RollbackExecutor
from triade.runtime.governed_capability import GovernedFileWriteCapability

ROOT = Path(__file__).resolve().parents[1]
TRIADE_ENTRYPOINT_KIND = "manual_diagnostic"

def main() -> int:
    recovery = json.loads((ROOT / "reports/evolution/admission_recovery_latest.json").read_text())
    case = Path(recovery["artifact_ref"]).resolve()
    if not recovery["truth"] or not case.is_relative_to(ROOT / "artifacts/evolution"):
        raise ValueError("verified_owned_recovery_required")
    spec = recovery["rollback_spec"]
    for key in ("target", "backup_ref", "workspace"):
        if not Path(spec[key]).resolve().is_relative_to(case):
            raise ValueError("rollback_outside_owned_case")
    target, backup = Path(spec["target"]), Path(spec["backup_ref"])
    original = backup.read_bytes()
    if hashlib.sha256(original).hexdigest() != recovery["baseline_sha256"]:
        raise ValueError("baseline_backup_changed")
    db = case.parent / "learning.db"
    source = json.loads((ROOT / "reports/evolution/admission_productive_use_latest.json").read_text())
    candidate_id = source.get("candidate_id") or ""
    if not candidate_id:
        prior = json.loads((ROOT / "reports/evolution/productive_learning_chain_v3.json").read_text())
        candidate_id = prior["candidate_id"]
    run_id = uuid4().hex
    capability = "bounded_configuration:" + case.name
    def measure(expression: str, subject: str) -> EvaluationRun:
        results = []
        for value in (34, 41, 52, 63, 79):
            probe = build_transfer_probe(db, candidate_id, value)
            if probe is None:
                raise ValueError("independent_probe_unavailable")
            score = float(probe.evaluator(json.dumps({"expression": expression})))
            results.append(MetricResult(str(value), score, score == 1, expression, "independent SQLite constraint"))
        return EvaluationRun(uuid4().hex, "bounded-config-transfer", "1", subject, tuple(results), sum(r.score for r in results)/len(results), utc_now())
    baseline = measure(json.loads(original)["expression"], str(target))
    candidate = measure(json.loads(target.read_bytes())["expression"], "inferior:" + run_id)
    output = ROOT / "reports/evolution/admission_rollback_latest.json"
    previous = json.loads(output.read_text()) if output.exists() else None
    resume = bool(previous and previous.get("rollback", {}).get("status") == "failed"
        and previous.get("baseline_restored") and target.read_bytes() == original)
    if resume:
        # Resume the recorded operation after a receipt serialization failure;
        # do not pretend the already restored target is still an inferior trial.
        output.with_name("admission_rollback_failed-" + previous["plan"]["rollback_id"] + ".json").write_text(output.read_text())
        run_id = previous["plan"]["rollback_id"]
        candidate = EvaluationRun(**{**previous["candidate"], "results":tuple(MetricResult(**r) for r in previous["candidate"]["results"])})
    gate = RegressionGate(db)
    gate.record_stable_state(capability, baseline)
    report = gate.evaluate(report_id=run_id + ("-resume" if resume else ""), candidate_id=candidate.subject_id, capability=capability,
        baseline=baseline, candidate=candidate,
        policies=tuple(MetricPolicy(r.case_id, severity="critical") for r in baseline.results),
        metadata={"correlation_id":recovery["correlation_id"], "scope":"paired measurement of preserved baseline and actual inferior configuration"})
    if report.decision != "fail":
        raise RuntimeError("candidate_regression_not_detected")
    executor = RollbackExecutor(db)
    receipts = []
    def restore(request: dict) -> dict:
        receipt = GovernedFileWriteCapability.rollback_from_spec(spec)
        receipts.append(receipt.model_dump(mode="json"))
        return {"applied":receipt.verified, "before_state":{"subject_id":candidate.subject_id},
            "after_state":{"subject_id":str(target), "sha256":hashlib.sha256(target.read_bytes()).hexdigest()}}
    executor.register_handler(capability, restore)
    plan = executor.get_plan(run_id) if resume else executor.plan(rollback_id=run_id, capability=capability, candidate_id=candidate.subject_id,
        report_id=report.report_id, target=gate.rollback_target(capability),
        reason="objective reserved-task regression", requested_by="bounded verification driver")
    outcome = executor.execute(plan.rollback_id)
    restored = measure(json.loads(target.read_bytes())["expression"], str(target))
    truth = (outcome.status == "applied" and target.read_bytes() == original
        and baseline.aggregate_score > candidate.aggregate_score
        and restored.aggregate_score == baseline.aggregate_score == 1)
    payload = {"timestamp":utc_now(), "tested_source_sha":subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip(),
        "correlation_id":recovery["correlation_id"], "baseline":baseline.to_dict(), "candidate":candidate.to_dict(),
        "regression":report.to_dict(), "plan":plan.to_dict(), "rollback":outcome.to_dict(),
        "receipts":receipts, "restored":restored.to_dict(), "baseline_restored":target.read_bytes()==original,
        "scope":"existing bounded experiment configuration; no identity, stable knowledge or source changes", "truth":truth}
    (ROOT / "reports/evolution/admission_rollback_latest.json").write_text(json.dumps(payload,indent=2),encoding="utf-8")
    print(json.dumps({"truth":truth,"baseline":baseline.aggregate_score,"candidate":candidate.aggregate_score,"restored":restored.aggregate_score}))
    return 0 if truth else 1

if __name__ == "__main__":
    raise SystemExit(main())
