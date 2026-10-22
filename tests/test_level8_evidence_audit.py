import json

import pytest

from scripts.level8_audit import DIMENSIONS, calculate, load_evidence


def test_unproven_gates_do_not_award_points():
    assert calculate({})["score"] == 0
    assert calculate({})["LEVEL_8_CANDIDATE"] is False


@pytest.mark.parametrize("gate,cap", [("tests", 7), ("runtime_e2e", 6.5), ("error_recovery", 7.5), ("learning_longitudinal", 7.5)])
def test_missing_critical_gate_caps_score(gate, cap):
    gates = {g: "PASS" for values in DIMENSIONS.values() for g in values}
    gates[gate] = "PENDING"
    result = calculate(gates)
    assert result["score"] <= cap
    assert not result["LEVEL_8_CANDIDATE"]


def test_stale_and_unstamped_reports_rejected(tmp_path):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"git_sha": "old", "timestamp": "now", "truth": True}))
    assert not load_evidence(path, "current")[1]["accepted"]
    path.write_text(json.dumps({"git_sha": "current", "truth": True}))
    assert not load_evidence(path, "current")[1]["accepted"]


def test_invalid_report_not_success(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("not json")
    assert load_evidence(path, "current")[0] == {}

def test_external_ci_exception_does_not_mask_missing_learning():
    gates={g:'PASS' for values in DIMENSIONS.values() for g in values}
    gates['ci']='RED-EXTERNAL'
    assert calculate(gates)['LEVEL_8_CANDIDATE']
    gates['learning_longitudinal']='FAIL'
    assert not calculate(gates)['LEVEL_8_CANDIDATE']

def test_direct_audit_cli_loads_closure_modules(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip()
    # Protocol intentionally proves nothing; it exercises the direct CLI import.
    (tmp_path/'background_autonomy_v2.json').write_text(json.dumps({'git_sha':sha,'timestamp':'2026-10-07T00:00:00+00:00','observations':[]}))
    result=subprocess.run([sys.executable,str(root/'scripts/level8_audit.py'),'--report-dir',str(tmp_path)],cwd=tmp_path,capture_output=True,text=True,check=False)
    assert result.returncode==1
    assert 'Traceback' not in result.stderr
    assert json.loads((tmp_path/'final_score.json').read_text())['LEVEL_8_CANDIDATE'] is False


def test_partial_protocols_do_not_certify_complete_circuits(tmp_path):
    from pathlib import Path

    from scripts.level8_audit import closure_gates
    root = Path(__file__).resolve().parents[1]
    # Unit-test historical protocol scope independent of changing source hashes.
    # These temporary inputs are NOT published as runtime certification.
    for name in ('recovery_end_to_end.json', 'background_autonomy_v2.json'):
        body = json.loads((root / 'reports/level8' / name).read_text())
        body['git_sha'] = 'unit-fixture'
        (tmp_path / name).write_text(json.dumps(body))
    gates, _ = closure_gates(tmp_path, 'unit-fixture')
    assert gates['isolated_task_and_api_recovery'] == 'PASS'
    assert gates['error_recovery'] == 'PENDING'
    assert gates['maintenance_autonomy'] == 'PASS'
    assert gates['background_autonomy'] == 'PENDING'
