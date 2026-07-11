from pathlib import Path

path = Path("triade/learning/pipeline.py")
text = path.read_text(encoding="utf-8")

import_marker = "from triade.memory.trust_store import TrustLevelStore\n"
import_line = "from triade.learning.evidence_bridge import LearningEvidenceBridge\n"
if import_line not in text:
    if import_marker not in text:
        raise RuntimeError("import marker not found")
    text = text.replace(import_marker, import_marker + import_line, 1)

init_marker = "        self.governance = SemanticMemoryGovernance(db_path=self.db_path)\n"
init_line = "        self.evidence_bridge = LearningEvidenceBridge(db_path=self.db_path)\n"
if init_line not in text:
    if init_marker not in text:
        raise RuntimeError("init marker not found")
    text = text.replace(init_marker, init_marker + init_line, 1)

promotion_old = '''        if (use_count >= self.MIN_RUN_USES and avg_score >= self.MIN_OUTCOME_SCORE
                and row["status"] == "verified"):
            self._update(
                candidate_id, status="validated_in_runs",
                note_step="validated_in_runs",
                note_payload={
                    "decision": "validated_in_runs",
                    "run_use_count": use_count,
                    "avg_outcome_score": avg_score,
                    "at": utc_now(),
                },
            )
'''
promotion_new = '''        if (use_count >= self.MIN_RUN_USES and avg_score >= self.MIN_OUTCOME_SCORE
                and row["status"] == "verified"):
            evidence = self.evidence_bridge.require_improvement(candidate_id)
            self._update(
                candidate_id, status="validated_in_runs",
                note_step="validated_in_runs",
                note_payload={
                    "decision": "validated_in_runs",
                    "run_use_count": use_count,
                    "avg_outcome_score": avg_score,
                    "measurement_decision": evidence["decision"],
                    "measurement_artifact_ref": evidence.get("artifact_ref"),
                    "at": utc_now(),
                },
            )
'''
if promotion_old in text:
    text = text.replace(promotion_old, promotion_new, 1)
elif promotion_new not in text:
    raise RuntimeError("promotion marker not found")

consolidate_marker = '''    def consolidate(self, candidate_id: str, approved_by: str = "", auto_consolidate: bool = True) -> dict[str, Any]:
        row = self._require(candidate_id)
'''
consolidate_new = '''    def consolidate(self, candidate_id: str, approved_by: str = "", auto_consolidate: bool = True) -> dict[str, Any]:
        row = self._require(candidate_id)
        measurement_evidence = self.evidence_bridge.require_improvement(candidate_id)
'''
if consolidate_marker in text:
    text = text.replace(consolidate_marker, consolidate_new, 1)
elif consolidate_new not in text:
    raise RuntimeError("consolidate marker not found")

metadata_old = '            metadata={"learning_candidate_id": candidate_id, "approved_by": approver},\n'
metadata_new = '            metadata={"learning_candidate_id": candidate_id, "approved_by": approver, "measurement_evidence": measurement_evidence.get("comparison")},\n'
if metadata_old in text:
    text = text.replace(metadata_old, metadata_new, 1)
elif metadata_new not in text:
    raise RuntimeError("metadata marker not found")

get_old = '''    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM learning_queue WHERE candidate_id = ?", (candidate_id,)).fetchone()
        return self._decode(dict(row)) if row else None
'''
get_new = '''    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM learning_queue WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if not row:
            return None
        candidate = self._decode(dict(row))
        candidate["measurement_evidence"] = self.evidence_bridge.get(candidate_id)
        return candidate
'''
if get_old in text:
    text = text.replace(get_old, get_new, 1)
elif get_new not in text:
    raise RuntimeError("get_candidate marker not found")

doctor_old = '                "consolidation_requires": ["status=verified_or_validated_in_runs", "source_ref", "risk!=critical", "run_use_count>=3", "avg_outcome_score>=0.70"],\n'
doctor_new = '                "consolidation_requires": ["status=verified_or_validated_in_runs", "source_ref", "risk!=critical", "run_use_count>=3", "avg_outcome_score>=0.70", "measurement_decision=improved", "critical_regressions=0"],\n'
if doctor_old in text:
    text = text.replace(doctor_old, doctor_new, 1)
elif doctor_new not in text:
    raise RuntimeError("doctor marker not found")

path.write_text(text, encoding="utf-8")
