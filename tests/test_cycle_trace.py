from triade.observability.cycle_trace import CognitiveCycleTrace


def test_cycle_trace_preserves_order_and_evidence() -> None:
    trace = CognitiveCycleTrace(run_id="run-test", cycle_id=1)
    trace.record_stage("hardware", status="ok", evidence_ref="health:1")
    trace.record_stage("metabolism", status="running", cycle_count=2)
    trace.record_stage("central", status="planned", evidence_ref="plan:1")
    trace.finish()

    payload = trace.to_dict()
    assert payload["run_id"] == "run-test"
    assert payload["stage_order"][0] == "hardware"
    assert payload["observed_stage_count"] == 4
    assert payload["evidence_refs"] == ["health:1", "plan:1"]
    assert payload["complete"] is False


def test_cycle_trace_rejects_unknown_stage() -> None:
    trace = CognitiveCycleTrace(run_id="run-test")
    try:
        trace.record_stage("unknown", status="ok")
    except ValueError as exc:
        assert "unknown cognitive stage" in str(exc)
    else:
        raise AssertionError("unknown stages must be rejected")
