from triade.core.internal_runtime import _is_expected_measurement_gate_signal


def test_measurement_gate_is_governance_signal_not_runtime_error():
    error = {
        "task_type": "learning_usage.mark_used",
        "message": "No existe evidencia Measurement Core para el candidato",
        "payload": {},
    }
    assert _is_expected_measurement_gate_signal(error) is True
