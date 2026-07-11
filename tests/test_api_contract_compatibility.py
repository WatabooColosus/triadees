from apps.routes import _legacy_heartbeat_truth, _legacy_ollama_status


def test_ollama_status_keeps_internal_detail_and_legacy_public_value():
    result = _legacy_ollama_status({"status": "degraded_no_ollama", "ok": False})

    assert result["status"] == "degraded"
    assert result["internal_status"] == "degraded_no_ollama"
    assert result["ok"] is False


def test_ollama_status_leaves_known_values_unchanged():
    result = _legacy_ollama_status({"status": "ok", "ok": True})

    assert result["status"] == "ok"
    assert result["internal_status"] == "ok"


def test_heartbeat_truth_maps_light_background_without_losing_truth():
    internal = "Autonomía full_local_guarded configurada · degradada a light_background por gobernador"
    result = _legacy_heartbeat_truth({"heartbeat_truth": internal})

    assert result["heartbeat_truth"] == (
        "Autonomía full_local_guarded configurada · degradada a balanced_background por gobernador"
    )
    assert result["internal_heartbeat_truth"] == internal


def test_heartbeat_truth_leaves_other_states_unchanged():
    truth = "Runtime activo con ciclos recientes"
    result = _legacy_heartbeat_truth({"heartbeat_truth": truth})

    assert result["heartbeat_truth"] == truth
    assert result["internal_heartbeat_truth"] == truth
