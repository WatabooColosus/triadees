from pathlib import Path

path = Path("triade/learning/pipeline.py")
text = path.read_text(encoding="utf-8")

old_head = '''    def consolidate(self, candidate_id: str, approved_by: str = "", auto_consolidate: bool = True) -> dict[str, Any]:
        row = self._require(candidate_id)
        measurement_evidence = self.evidence_bridge.require_improvement(candidate_id)
        model_guard = self._model_guard("stable_consolidation", human_approval=approved_by)
'''
new_head = '''    def consolidate(self, candidate_id: str, approved_by: str = "", auto_consolidate: bool = True) -> dict[str, Any]:
        row = self._require(candidate_id)
        model_guard = self._model_guard("stable_consolidation", human_approval=approved_by)
'''
if old_head in text:
    text = text.replace(old_head, new_head, 1)
elif new_head not in text:
    raise RuntimeError("consolidate head marker not found")

anchor = '''        if avg_score < self.MIN_OUTCOME_SCORE:
            raise ValueError(
                f"No se consolida sin score suficiente: "
                f"avg_outcome_score={avg_score:.3f}, mínimo={self.MIN_OUTCOME_SCORE}."
            )

        explicit_approver = (approved_by or "").strip()
'''
replacement = '''        if avg_score < self.MIN_OUTCOME_SCORE:
            raise ValueError(
                f"No se consolida sin score suficiente: "
                f"avg_outcome_score={avg_score:.3f}, mínimo={self.MIN_OUTCOME_SCORE}."
            )

        measurement_evidence = self.evidence_bridge.require_improvement(candidate_id)

        explicit_approver = (approved_by or "").strip()
'''
if anchor in text:
    text = text.replace(anchor, replacement, 1)
elif replacement not in text:
    raise RuntimeError("measurement gate insertion marker not found")

path.write_text(text, encoding="utf-8")
