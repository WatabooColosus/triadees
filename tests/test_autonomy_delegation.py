"""Tests de Autonomía Delegada Gobernada."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from triade.core.system_zones import classify_path, REPO_ROOT
from triade.core.autonomy_budget import build_autonomy_budget, LEVEL_PERCENT, LEVELS
from triade.core.integrity_verifier import build_integrity_snapshot, verify_integrity_change
from triade.core.quarantine_trash import trash_path, restore_trash_item, list_trash
from triade.core.safe_file_ops import safe_create_file, safe_patch_file, safe_move_file, safe_delete_file
from triade.core.delegated_action_planner import plan_delegated_action


# ── FASE 1: System Zones ─────────────────────────────────────────────


def test_classify_path_blocks_git():
    result = classify_path(".git/config")
    assert result["zone"] == "forbidden"
    assert result["can_read"] is False
    assert result["can_modify"] is False


def test_classify_path_blocks_env():
    result = classify_path(".env")
    assert result["zone"] == "forbidden"
    assert result["can_read"] is False


def test_classify_path_blocks_identity_core():
    result = classify_path("triade/memory/identity_core.json")
    assert result["zone"] == "forbidden" or result["zone"] == "red"
    assert result["can_modify"] is False


def test_classify_path_green_default():
    result = classify_path("runs/test_run.txt")
    assert result["zone"] == "green"
    assert result["can_create"] is True


def test_classify_path_yellow():
    result = classify_path("triade/core/central.py")
    assert result["zone"] == "yellow"
    assert result["can_modify"] is True


def test_classify_path_red():
    result = classify_path("triade/memory/triade.db")
    assert result["zone"] == "red"
    assert result["can_read"] is True
    assert result["can_create"] is False
    assert result["requires_human_approval"] is True


# ── FASE 2: Autonomy Budget ──────────────────────────────────────────


def test_budget_observe_only_read_only():
    budget = build_autonomy_budget("observe_only")
    assert budget["autonomy_percent"] == 0
    assert "create" not in budget["allowed_actions"]
    assert "read" in budget["allowed_actions"]
    assert budget["can_modify_identity_core"] is False
    assert budget["can_modify_git"] is False


def test_budget_full_local_guarded_no_direct_delete():
    budget = build_autonomy_budget("full_local_guarded")
    assert budget["autonomy_percent"] == 80
    assert budget["can_delete_directly"] is False
    assert budget["delete_strategy"] == "trash_only"
    assert "delete_to_trash" in budget["allowed_actions"]
    assert "run_tests" in budget["allowed_actions"]
    assert "run_build" in budget["allowed_actions"]


def test_budget_safe_write_green_only():
    budget = build_autonomy_budget("safe_write")
    assert budget["allowed_zones"] == ["green"]
    assert "yellow" not in budget["allowed_zones"]


def test_budget_project_maintenance():
    budget = build_autonomy_budget("project_maintenance")
    assert "green" in budget["allowed_zones"]
    assert "yellow" in budget["allowed_zones"]


# ── FASE 3: Integrity Verifier ───────────────────────────────────────


def test_integrity_snapshot_has_counts():
    snap = build_integrity_snapshot([str(REPO_ROOT / "triade" / "core" / "system_zones.py")])
    assert snap["files_count"] > 0
    assert snap["total_bytes"] > 0
    assert "files" in snap
    assert "zone_summary" in snap


def test_integrity_detects_unplanned_hash_change():
    tmp = tempfile.mktemp(dir=str(REPO_ROOT), suffix=".py")
    Path(tmp).write_text("original content")
    before = build_integrity_snapshot([tmp])
    Path(tmp).write_text("modified content")
    after = build_integrity_snapshot([tmp])
    plan = {"action_type": "read", "target_paths": [tmp], "zones": ["green"], "max_bytes_per_cycle": 100000}
    result = verify_integrity_change(before, after, plan)
    assert result["hash_changed_unexpected"] != []
    assert result["requires_human_review"] is True
    os.unlink(tmp)


def test_integrity_planned_patch_ok():
    tmp = tempfile.mktemp(dir=str(REPO_ROOT), suffix=".py")
    Path(tmp).write_text("original content")
    before = build_integrity_snapshot([tmp])
    Path(tmp).write_text("modified content")
    after = build_integrity_snapshot([tmp])
    plan = {"action_type": "patch", "target_paths": [tmp], "zones": ["green"], "max_bytes_per_cycle": 100000}
    result = verify_integrity_change(before, after, plan)
    assert "modified" in str(result)
    os.unlink(tmp)


# ── FASE 4: Quarantine Trash ─────────────────────────────────────────


def test_trash_restore_roundtrip():
    tmp = tempfile.mktemp(dir=str(REPO_ROOT))
    Path(tmp).write_text("test roundtrip content")
    result = trash_path(tmp, reason="test_roundtrip", run_ref="test-run")
    assert result["status"] == "ok"
    assert Path(tmp).exists() is False

    manifest_path = result["manifest_path"]
    restore = restore_trash_item(manifest_path)
    assert restore["status"] == "ok"
    assert Path(tmp).exists() is True
    assert Path(tmp).read_text() == "test roundtrip content"
    os.unlink(tmp)


def test_trash_blocks_forbidden():
    tmp = str(REPO_ROOT / ".git" / "test_trash_blocked_tmp")
    Path(tmp).write_text("blocked")
    result = trash_path(tmp, reason="should block")
    assert result["status"] == "blocked_forbidden_zone"
    Path(tmp).unlink(missing_ok=True)


def test_trash_list():
    tmp = tempfile.mktemp(dir=str(REPO_ROOT))
    Path(tmp).write_text("list test content")
    trash_path(tmp, reason="test_list", run_ref="test-run")
    result = list_trash(limit=10)
    assert result["total_count"] >= 1
    assert len(result["items"]) >= 1


# ── FASE 5: Safe File Ops ────────────────────────────────────────────


def test_safe_create_file_dry_run_default():
    target = tempfile.mktemp(dir=str(REPO_ROOT))
    result = safe_create_file(target, "hello world", "safe_write", dry_run=True)
    assert result["status"] == "dry_run"
    assert Path(target).exists() is False


def test_safe_create_file_forbidden_zone():
    target = str(REPO_ROOT / ".git" / "test-blocked-safe-create")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    result = safe_create_file(target, "content", "full_local_guarded", dry_run=False)
    assert result["status"] == "blocked_forbidden_zone"
    os.unlink(target) if Path(target).exists() else None


def test_safe_delete_moves_to_trash_not_unlink():
    tmp = tempfile.mktemp(dir=str(REPO_ROOT))
    Path(tmp).write_text("delete test content")
    result = safe_delete_file(tmp, "project_maintenance", dry_run=False, reason="test delete")
    assert result["status"] == "ok"
    assert Path(tmp).exists() is False
    # Should be in trash
    trash = list_trash(limit=50)
    found = any(tmp.endswith(t.get("original_path", "")) for t in trash["items"])
    assert found, "El archivo debería estar en la papelera"


def test_safe_delete_dry_run():
    tmp = tempfile.mktemp(dir=str(REPO_ROOT))
    Path(tmp).write_text("dry run delete")
    result = safe_delete_file(tmp, "project_maintenance", dry_run=True)
    assert result["status"] == "dry_run"
    assert Path(tmp).exists() is True
    os.unlink(tmp)


def test_safe_move_requires_zone_permission():
    src = tempfile.mktemp(dir=str(REPO_ROOT))
    dst = tempfile.mktemp(dir=str(REPO_ROOT))
    Path(src).write_text("move test")
    result = safe_move_file(src, dst, "observe_only", dry_run=False)
    assert result["status"] == "blocked_budget"
    os.unlink(src)


def test_safe_patch_dry_run():
    tmp = tempfile.mktemp(dir=str(REPO_ROOT))
    Path(tmp).write_text("original")
    result = safe_patch_file(tmp, "patched", "project_maintenance", dry_run=True)
    assert result["status"] == "dry_run"
    assert Path(tmp).read_text() == "original"
    os.unlink(tmp)


# ── FASE 6: Delegated Planner ────────────────────────────────────────


def test_delegated_plan_requires_human_for_red_zone():
    plan = plan_delegated_action("delete", ["triade/memory/triade.db"], "full_local_guarded")
    assert plan["human_approval_required"] is True
    assert plan["red_zones"] == ["triade/memory/triade.db"]


def test_delegated_plan_blocks_forbidden():
    plan = plan_delegated_action("create", [".git/config"], "full_local_guarded")
    assert plan["allowed"] is False
    assert "prohibida" in (plan["blocked_reason"] or "").lower()


def test_delegated_plan_observe_blocks_write():
    plan = plan_delegated_action("create", ["runs/test.txt"], "observe_only")
    assert plan["allowed"] is False


def test_delegated_plan_full_local_guarded_allows_green():
    plan = plan_delegated_action("create", ["runs/test.txt"], "full_local_guarded")
    assert plan["allowed"] is True
    assert "green" in plan["zones"]


def test_delegated_plan_risk_score():
    plan = plan_delegated_action("refactor", ["triade/core/central.py"], "repo_refactor")
    assert plan["risk_score"] > 0.3
    assert plan["dry_run_required"] is True


def test_identity_core_never_modified():
    """El presupuesto nunca permite modificar identity_core."""
    for level in LEVELS:
        budget = build_autonomy_budget(level)
        assert budget["can_modify_identity_core"] is False, f"Nivel {level} no debe modificar identity_core"
    # system_zones también bloquea
    info = classify_path("identity_core.json")
    assert info["can_modify"] is False
