from triade.core.central import Central
from triade.core.contracts import CrystalPacket, InputPacket, MemoryPacket, SignalPacket


def test_central_prompt_includes_authorized_qualia_context() -> None:
    memory = MemoryPacket(run_id="run-c", semantic_recall={"qualia_bus": {"status": "ok", "latest_qualia_state": {"risk": 0.2}, "central_knowledge_packets": [{"claim": "hipótesis"}], "relevant_signals": [{"signal_type": "x"}], "policy": "solo hipótesis"}})
    prompt = Central._build_prompt(
        "Tríade Ω",
        InputPacket(user_input="Qué sabes?", run_id="run-c"),
        SignalPacket(run_id="run-c", intent="conversation", tone="constructive", urgency="low", risk="low"),
        memory,
        CrystalPacket(run_id="run-c"),
        Central().plan(InputPacket(user_input="Qué sabes?", run_id="run-c"), SignalPacket(run_id="run-c", intent="conversation", tone="constructive", urgency="low", risk="low"), memory, CrystalPacket(run_id="run-c")),
    )
    assert "QualiaBus autorizado" in prompt
    assert "solo hipótesis" in prompt
