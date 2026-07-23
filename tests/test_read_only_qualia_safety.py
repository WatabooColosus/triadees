from unittest.mock import patch

from triade.core.contracts import SignalPacket
from triade.core.runner import TriadeRunner


def test_read_only_capability_question_is_not_blocked_by_historical_qualia(tmp_path):
    runner = TriadeRunner(runs_dir=tmp_path / "runs", db_path=tmp_path / "triade.db", use_ollama=False)
    critical = [{"intensity": 1.0, "risk": 1.0, "urgency": 1.0, "tone_hint": "cautious"}]
    with patch("triade.core.runner.QualiaStore.list_signals", return_value=critical):
        result = runner.run("¿Puedes usar Internet y aprender?", semantic_recall_enabled=False)
    assert result["safety"]["status"] != "requires_human_approval"
    assert result["response"].startswith("Soy Tríade Ω")
