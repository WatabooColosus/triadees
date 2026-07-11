from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old in text:
        return text.replace(old, new, 1)
    if new in text:
        return text
    raise RuntimeError(f"marker not found: {label}")


trust = Path("tests/test_trust_levels.py")
text = trust.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from triade.learning.pipeline import LearningPipeline\n",
    "from triade.learning.pipeline import LearningPipeline\nfrom tests.learning_evidence_helpers import attach_improved_evidence\n",
    "trust import",
)
for marker in (
    '        pipe.verify(cid)\n        for i in range(5):\n            pipe.mark_used_in_run(cid, f"run-trust-{i}", outcome_score=0.85)\n',
    '        pipe.verify(cid)\n        for i in range(5):\n            pipe.mark_used_in_run(cid, f"run-medium-{i}", outcome_score=0.80)\n',
    '        pipe.verify(cid)\n        for i in range(5):\n            pipe.mark_used_in_run(cid, f"run-high-{i}", outcome_score=0.90)\n',
    '        pipe.verify(cid)\n        for i in range(5):\n            pipe.mark_used_in_run(cid, f"run-human-{i}", outcome_score=0.85)\n',
):
    replacement = marker.replace("        for i", "        attach_improved_evidence(pipe, cid, capability=\"trust_consolidation\")\n        for i")
    text = replace_once(text, marker, replacement, marker.splitlines()[-1])
trust.write_text(text, encoding="utf-8")

worker = Path("tests/test_worker_stable_consolidation_review.py")
text = worker.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from triade.learning.pipeline import LearningPipeline\n",
    "from triade.learning.pipeline import LearningPipeline\nfrom tests.learning_evidence_helpers import attach_improved_evidence\n",
    "worker import",
)
marker = '''        pipe.evaluate(cid)
        pipe.verify(cid)
        for j in range(3):
            pipe.mark_used_in_run(cid, f"run-{i}-{j}", outcome_score=0.85)
'''
replacement = '''        pipe.evaluate(cid)
        pipe.verify(cid)
        attach_improved_evidence(pipe, cid, capability="worker_stable_consolidation")
        for j in range(3):
            pipe.mark_used_in_run(cid, f"run-{i}-{j}", outcome_score=0.85)
'''
text = replace_once(text, marker, replacement, "worker stable evidence")
worker.write_text(text, encoding="utf-8")
