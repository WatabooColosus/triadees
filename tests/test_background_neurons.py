from triade.core.background_neurons import candidates_from_system_debt


def test_missing_federation_telemetry_does_not_invent_android_debt() -> None:
    candidates = candidates_from_system_debt({"source": "continuous_pulse", "status": "ok"})

    assert all("Android" not in str(item.get("display_name")) for item in candidates)


def test_declared_federation_telemetry_can_report_android_debt() -> None:
    candidates = candidates_from_system_debt(
        {"federation": {"android_native_online": 0, "android_llm_hosts": 0}}
    )

    names = {str(item.get("display_name")) for item in candidates}
    assert "Arquitecta de Nodos Android" in names
    assert "Formadora de Hosts LLM Android" in names
