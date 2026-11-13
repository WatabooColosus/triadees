from unittest.mock import patch

from triade.core.internal_runtime import _is_expected_measurement_gate_signal


def test_measurement_gate_is_governance_signal_not_runtime_error():
    error = {
        "task_type": "learning_usage.mark_used",
        "message": "No existe evidencia Measurement Core para el candidato",
        "payload": {},
    }
    assert _is_expected_measurement_gate_signal(error) is True


def test_heartbeat_does_not_promote_info_event_to_latest_error(tmp_path):
    from triade.core.internal_runtime import build_runtime_heartbeat

    with patch("triade.core.error_bus.query_internal_errors", return_value=[]):
        heartbeat = build_runtime_heartbeat(
            db_path=tmp_path / "triade.db",
            runs_dir=tmp_path / "runs",
            limit=5,
        )

    assert heartbeat["latest_error"] is None
