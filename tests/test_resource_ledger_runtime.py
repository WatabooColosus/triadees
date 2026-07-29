from triade.runtime.resource_ledger import ResourceLedger


def test_ledger_aggregates_and_degrades_at_thresholds(tmp_path):
    ledger = ResourceLedger(tmp_path / "ledger.db", {"cpu_minutes_daily": 1})
    ledger.record(task_id="t", worker_id="w", cpu_seconds=43, success=True)
    assert ledger.policy()["mode"] == "cost_reduced"
    assert ledger.allows("deep_evaluation") is False
    ledger.record(task_id="t2", worker_id="w", cpu_seconds=18, success=True)
    policy = ledger.policy()
    assert policy["mode"] == "observe_only"
    assert policy["allowed_classes"] == ["heartbeat", "maintenance", "safety"]


def test_ledger_records_all_resource_dimensions(tmp_path):
    ledger = ResourceLedger(tmp_path / "ledger.db")
    entry = ledger.record(task_id="t", worker_id="w", neuron_id="n", cpu_seconds=2, gpu_seconds=3,
                          ram_peak_mb=10, vram_peak_mb=11, tokens_input=12, tokens_output=13,
                          network_bytes=14, disk_bytes_read=15, disk_bytes_written=16,
                          duration_seconds=17, model="local", estimated_energy_wh=18,
                          temperature_peak_c=45, success=False, task_class="research")
    assert entry > 0
    usage = ledger.daily_usage()
    assert usage["research_tasks_daily"] == 1
    assert usage["gpu_minutes_daily"] == 3 / 60
