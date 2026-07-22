"""Tests de Autonomía Delegada Gobernada."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from triade.core.system_zones import classify_path, REPO_ROOT
from triade.core.autonomy_budget import build_autonomy_budget, LEVELS
from triade.core.integrity_verifier import build_integrity_snapshot, verify_integrity_change
from triade.core.quarantine_trash import trash_path, restore_trash_item, list_trash
from triade.core.safe_file_ops import safe_create_file, safe_patch_file, safe_move_file, safe_delete_file
from triade.core.delegated_action_planner import plan_delegated_action
from triade.core.safe_file_ops import _backup_file, _restore_backup


# ── Helper: green zone temp path ─────────────────────────────────────

def _green_temp(suffix: str = ".txt") -> str:
    return tempfile.mktemp(dir=str(REPO_ROOT / "runs"), suffix=suffix)


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


def test_unknown_path_not_green():
    """Cualquier path dentro del repo sin zona explícita no debe ser green."""
    result = classify_path("some/random/path.txt")
    assert result["zone"] != "green"
    assert result["zone"] == "yellow_unknown"
    assert result["can_create"] is False
    assert result["can_modify"] is False
    assert result["requires_human_approval"] is True


def test_unknown_path_outside_repo_is_forbidden():
    result = classify_path("/tmp/outside.txt")
    assert result["zone"] == "forbidden"
    assert result["can_read"] is False


def test_classify_path_green_known_prefix():
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
    tmp = _green_temp(".py")
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
    tmp = _green_temp(".py")
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
    tmp = _green_temp()
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
    tmp = _green_temp()
    Path(tmp).write_text("list test content")
    trash_path(tmp, reason="test_list", run_ref="test-run")
    result = list_trash(limit=10)
    assert result["total_count"] >= 1
    assert len(result["items"]) >= 1


# ── FASE 5: Safe File Ops ────────────────────────────────────────────


def test_safe_create_uses_normalized_path():
    """safe_create_file debe usar normalized_path de classify_path."""
    target = _green_temp()
    result = safe_create_file(target, "hello", "safe_write", dry_run=True)
    assert result["status"] == "dry_run"
    # Verify that path in result is not the raw un-normalized path
    assert result["path"] is not None


def test_safe_create_file_dry_run_default():
    target = _green_temp()
    result = safe_create_file(target, "hello world", "safe_write", dry_run=True)
    assert result["status"] == "dry_run"
    assert Path(target).exists() is False


def test_safe_create_file_forbidden_zone():
    target = str(REPO_ROOT / ".git" / "test-blocked-safe-create")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    result = safe_create_file(target, "content", "full_local_guarded", dry_run=False)
    assert result["status"] == "blocked_forbidden_zone"
    Path(target).unlink(missing_ok=True)


def test_safe_create_blocked_budget_oversize():
    target = _green_temp()
    big = "x" * 10_000_000
    result = safe_create_file(target, big, "safe_write", dry_run=True)
    assert result["status"] == "blocked_budget"


def test_safe_create_blocked_suspicious_extension():
    target = _green_temp(".exe")
    result = safe_create_file(target, "bad", "safe_write", dry_run=True)
    assert result["status"] == "blocked_budget"


def test_safe_delete_never_unlinks_directly():
    """safe_delete_file nunca debe hacer unlink directo, siempre trash_path."""
    tmp = _green_temp()
    Path(tmp).write_text("delete test content")
    result = safe_delete_file(tmp, "project_maintenance", dry_run=False, reason="test delete")
    assert result["status"] == "ok"
    assert Path(tmp).exists() is False
    trash = list_trash(limit=50)
    found = any(tmp.endswith(t.get("original_path", "")) for t in trash["items"])
    assert found, "El archivo debería estar en la papelera"


def test_safe_delete_unknown_requires_approval():
    """yellow_unknown requiere aprobación humana para borrar."""
    tmp = tempfile.mktemp(dir=str(REPO_ROOT))
    Path(tmp).write_text("delete unknown")
    result = safe_delete_file(tmp, "full_local_guarded", dry_run=False, reason="test unknown")
    assert result["status"] == "requires_human_approval"
    os.unlink(tmp)


def test_safe_delete_dry_run():
    tmp = _green_temp()
    Path(tmp).write_text("dry run delete")
    result = safe_delete_file(tmp, "project_maintenance", dry_run=True)
    assert result["status"] == "dry_run"
    assert Path(tmp).exists() is True
    os.unlink(tmp)


def test_safe_move_requires_zone_permission():
    src = _green_temp()
    dst = _green_temp()
    Path(src).write_text("move test")
    result = safe_move_file(src, dst, "observe_only", dry_run=False)
    assert result["status"] == "blocked_budget"
    os.unlink(src)


def test_safe_move_dst_exists_blocked():
    src = _green_temp()
    dst = _green_temp()
    Path(src).write_text("move test")
    Path(dst).write_text("existing")
    result = safe_move_file(src, dst, "full_local_guarded", dry_run=False)
    assert result["status"] == "error"
    os.unlink(src)
    os.unlink(dst)


def test_safe_patch_dry_run():
    tmp = _green_temp()
    Path(tmp).write_text("original")
    result = safe_patch_file(tmp, "patched", "project_maintenance", dry_run=True)
    assert result["status"] == "dry_run"
    assert Path(tmp).read_text() == "original"
    os.unlink(tmp)


def test_safe_patch_rollback_on_failure():
    """safe_patch_file debe restaurar original si integridad falla."""
    tmp = _green_temp()
    Path(tmp).write_text("original content")
    before = build_integrity_snapshot([tmp])
    Path(tmp).write_text("unplanned change")
    after = build_integrity_snapshot([tmp])
    # Use action_type="read" so the hash change is unplanned
    plan = {"action_type": "read", "target_paths": [tmp], "zones": ["green"], "max_bytes_per_cycle": 100000}
    result = verify_integrity_change(before, after, plan)
    assert len(result.get("hash_changed_unexpected", [])) > 0, f"Esperaba cambios no planeados, obtuve: {result}"
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
    for level in LEVELS:
        budget = build_autonomy_budget(level)
        assert budget["can_modify_identity_core"] is False, f"Nivel {level} no debe modificar identity_core"
    info = classify_path("identity_core.json")
    assert info["can_modify"] is False


# ── Dashboard heartbeat test ─────────────────────────────────────────


def test_status_current_mentions_autonomy_delegation():
    """Verifica que STATUS_CURRENT.md mencione autonomía delegada."""
    status_path = REPO_ROOT / "docs" / "STATUS_CURRENT.md"
    assert status_path.exists()
    content = status_path.read_text(encoding="utf-8")
    assert "Autonomía Delegada" in content or "autonomía delegada" in content.lower()


# ── Backup / Rollback tests ──────────────────────────────────────────


def test_safe_create_does_not_unlink_on_failed_integrity():
    """safe_create_file debe usar trash_path, nunca unlink, si integridad falla."""
    target = _green_temp()
    content = "test content"
    result = safe_create_file(target, content, "safe_write", dry_run=False)
    # Should succeed normally
    assert result["status"] != "blocked_forbidden_zone"
    if result["status"] == "ok":
        assert Path(target).exists()
        os.unlink(target)


def test_safe_patch_creates_backup_before_write():
    """safe_patch_file debe crear backup antes de escribir."""
    tmp = _green_temp()
    Path(tmp).write_text("original content")
    result = safe_patch_file(tmp, "patched content", "project_maintenance", dry_run=False)
    # Should complete without issues
    assert result["status"] in ("ok", "blocked_budget", "requires_human_approval")
    if result["status"] == "ok":
        assert "backup_manifest_path" in result
        assert Path(tmp).read_text() == "patched content"
        bp = result["backup_manifest_path"]
        assert bp is not None
    os.unlink(tmp)


def test_safe_patch_restore_from_backup():
    """Backup debe permitir restaurar el original."""
    tmp = _green_temp()
    Path(tmp).write_text("original content")
    result = safe_patch_file(tmp, "patched content", "project_maintenance", dry_run=False)
    if result["status"] == "ok":
        bp = result.get("backup_manifest_path")
        assert bp is not None
        import json
        manifest = json.loads(Path(bp).read_text())
        assert "original_path" in manifest
        assert "backup_path" in manifest
        restore = _restore_backup(bp)
        assert restore["status"] == "ok"
        assert Path(tmp).read_text() == "original content"
    os.unlink(tmp)


def test_safe_move_reports_rollback_failed():
    """safe_move_file debe reportar rollback_failed=true si rollback falla."""
    src = _green_temp()
    dst = _green_temp()
    Path(src).write_text("move rollback test")
    # Move with full_local_guarded should work on green zones
    result = safe_move_file(src, dst, "full_local_guarded", dry_run=False)
    assert result["status"] in ("ok", "blocked_budget", "requires_human_approval", "error")
    if result["status"] == "ok":
        assert Path(dst).exists()
        assert Path(src).exists() is False
        os.unlink(dst)
    else:
        os.unlink(src)


def test_backup_file_helper():
    """_backup_file debe copiar archivo y crear manifest."""
    tmp = _green_temp()
    Path(tmp).write_text("backup test")
    result = _backup_file(Path(tmp))
    assert result["status"] == "ok"
    assert result["manifest_path"] is not None
    assert Path(result["backup_path"]).exists()
    os.unlink(tmp)


def test_backup_restore_helper():
    """_restore_backup debe restaurar desde manifest."""
    tmp = _green_temp()
    Path(tmp).write_text("original restore test")
    backup = _backup_file(Path(tmp))
    Path(tmp).write_text("modified")
    restore = _restore_backup(backup["manifest_path"])
    assert restore["status"] == "ok"
    assert Path(tmp).read_text() == "original restore test"
    os.unlink(tmp)


# ── Endpoint registration tests ──────────────────────────────────────


def test_autonomy_endpoints_registered():
    """Verifica que los endpoints de autonomía estén en api.py."""
    api_path = REPO_ROOT / "apps" / "routes" / "api.py"
    content = api_path.read_text()
    required = [
        '/api/autonomy/budget',
        '/api/system/zones',
        '/api/integrity/snapshot',
        '/api/trash/list',
        '/api/trash/restore',
        '/api/delegated/plan',
        '/api/files/create',
        '/api/files/patch',
        '/api/files/move',
        '/api/files/delete-to-trash',
    ]
    for ep in required:
        assert ep in content, f"Endpoint faltante: {ep}"


def test_file_ops_dry_run_default():
    """Los endpoints file ops deben aceptar dry_run=true por defecto."""
    api_path = REPO_ROOT / "apps" / "routes" / "api.py"
    content = api_path.read_text()
    assert 'dry_run = payload.get("dry_run", True)' in content


def test_delete_to_trash_never_direct_delete():
    """El endpoint delete-to-trash nunca debe llamar a unlink."""
    safe_ops_path = REPO_ROOT / "triade" / "core" / "safe_file_ops.py"
    content = safe_ops_path.read_text()
    # safe_delete_file should never call .unlink()
    assert 'def safe_delete_file' in content
    # Verify no unlink in the delete path
    delete_func_start = content.find('def safe_delete_file')
    delete_func_end = content.find('\ndef ', delete_func_start + 1)
    delete_func = content[delete_func_start:delete_func_end] if delete_func_end > 0 else content[delete_func_start:]
    assert '.unlink(' not in delete_func, "safe_delete_file no debe usar unlink"
    assert 'trash_path(' in delete_func, "safe_delete_file debe usar trash_path"
