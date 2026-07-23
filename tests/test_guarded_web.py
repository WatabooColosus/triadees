import pytest

from triade.core.guarded_web import _assert_public_url, _clean_query, requests_web_research
from triade.core.permission_governor import build_permission_profile
from triade.core.resource_governor import decide_work_mode


def test_web_research_requires_explicit_request():
    assert requests_web_research("busca en internet la historia de Medellín") is True
    assert requests_web_research("cuéntame la historia de Medellín") is False
    assert _clean_query("busca en internet la historia de Medellín") == "la historia de Medellín"


def test_guard_blocks_private_hosts():
    with pytest.raises(ValueError):
        _assert_public_url("http://127.0.0.1:8010/private")
    with pytest.raises(ValueError):
        _assert_public_url("file:///etc/passwd")


def test_full_local_guarded_capabilities_are_consistent():
    probe = {
        "limits": {"ram_available_gb": 16, "disk_free_gb": 100, "tier": "high", "cpu_count": 8},
        "cpu": {"load_1min": 1.0}, "power": {"ac_connected": True, "battery_percent": 100},
        "thermal": {"thermal_status": "ok"}, "warnings": [],
    }
    result = decide_work_mode(probe, {"status": "ok", "can_reason": True, "can_embed": True}, "full_local_guarded")
    assert result["can_run_tests"] is True
    assert result["can_run_build"] is True
    assert result["can_research_web"] is True
    permissions = build_permission_profile("full_local_guarded")
    assert permissions["permissions"]["can_research_web"] is True
    assert permissions["permissions"]["can_run_shell"] is False
    assert permissions["permissions"]["can_run_safe_shell"] is True
