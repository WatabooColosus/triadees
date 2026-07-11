from pathlib import Path

path = Path("tests/test_triade_neuron_learning_e2e.py")
text = path.read_text(encoding="utf-8")

import_anchor = "from triade.learning.pipeline import LearningPipeline\n"
imports = "from triade.evaluation import EvaluationComparison, EvaluationRun, MetricResult\n"
if imports not in text:
    text = text.replace(import_anchor, imports + import_anchor, 1)

helper_anchor = "\ndef make_db(tmp_path: Path) -> Path:\n"
helper = '''\ndef _attach_improved_evidence(pipeline: LearningPipeline, cid: str) -> None:\n    subject = f"candidate:{cid}"\n    pipeline.evidence_bridge.declare_hypothesis(\n        cid,\n        hypothesis="El candidato mejora aprendizaje neuronal medible.",\n        capability="neuron_learning",\n        subject_id=subject,\n    )\n    baseline = EvaluationRun(\n        evaluation_id=f"base-{cid}",\n        suite_id="neuron-learning",\n        suite_version="1.0.0",\n        subject_id=subject,\n        results=(MetricResult("neuron-case", 0.0, False, False, True),),\n        aggregate_score=0.0,\n        created_at="2026-07-11T00:00:00Z",\n    )\n    candidate = EvaluationRun(\n        evaluation_id=f"candidate-{cid}",\n        suite_id="neuron-learning",\n        suite_version="1.0.0",\n        subject_id=subject,\n        results=(MetricResult("neuron-case", 1.0, True, True, True),),\n        aggregate_score=1.0,\n        created_at="2026-07-11T00:00:01Z",\n    )\n    comparison = EvaluationComparison(\n        baseline_evaluation_id=baseline.evaluation_id,\n        candidate_evaluation_id=candidate.evaluation_id,\n        baseline_score=0.0,\n        candidate_score=1.0,\n        absolute_delta=1.0,\n        percent_delta=None,\n        improved_cases=("neuron-case",),\n        degraded_cases=(),\n        critical_regressions=(),\n        decision="improved",\n    )\n    pipeline.evidence_bridge.record_comparison(\n        cid,\n        baseline=baseline,\n        candidate=candidate,\n        comparison=comparison,\n        artifact_ref=f"runs/learning_evidence/{cid}",\n    )\n\n'''
if "def _attach_improved_evidence" not in text:
    text = text.replace(helper_anchor, helper + helper_anchor, 1)

call_anchor = '''    pipeline.evaluate(cid)\n    pipeline.verify(cid)\n\n    output = SimpleNamespace(\n        response="Los sistemas distribuidos tolerantes a fallos son esenciales",\n'''
call_replacement = '''    pipeline.evaluate(cid)\n    pipeline.verify(cid)\n    _attach_improved_evidence(pipeline, cid)\n\n    output = SimpleNamespace(\n        response="Los sistemas distribuidos tolerantes a fallos son esenciales",\n'''
if call_anchor in text:
    text = text.replace(call_anchor, call_replacement, 1)
elif call_replacement not in text:
    raise RuntimeError("target E2E block not found")

assert_anchor = '''    assert c["status"] == "validated_in_runs"\n    assert c["run_use_count"] >= 3\n'''
assert_replacement = '''    assert c["status"] == "validated_in_runs"\n    assert c["measurement_evidence"]["decision"] == "improved"\n    assert c["run_use_count"] >= 3\n'''
if assert_anchor in text:
    text = text.replace(assert_anchor, assert_replacement, 1)

path.write_text(text, encoding="utf-8")
