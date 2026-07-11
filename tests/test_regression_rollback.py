from __future__ import annotations

from pathlib import Path

from triade.regression.rollback import RollbackExecutor


def target() -> dict[str, str]:
    return {
        "subject_id": "stable-v1",
        "evaluation_id": "eval-stable-v1",
        "suite_id": "learning-critical",
        "suite_version": "1.0.0",
    }


def test_executes_registered_rollback_and_persists_result(tmp_path: Path) -> None:
    executor = RollbackExecutor(tmp_path / "triade.db")
    executor.register_handler(
        "learning",
        lambda request: {
            "applied": True,
            "before_state": {"subject_id": "candidate-v2"},
            "after_state": {"subject_id": request["target"]["subject_id"]},
        },
    )
    executor.plan(
        rollback_id="rollback-1",
        capability="learning",
        candidate_id="candidate-1",
        report_id="report-1",
        target=target(),
        reason="critical regression",
        requested_by="central",
    )

    result = executor.execute("rollback-1")

    assert result.status == "applied"
    assert result.after_state["subject_id"] == "stable-v1"
    assert executor.get_result("rollback-1") == result
    assert executor.execute("rollback-1") == result


def test_rejects_execution_without_registered_handler(tmp_path: Path) -> None:
    executor = RollbackExecutor(tmp_path / "triade.db")
    executor.plan(
        rollback_id="rollback-2",
        capability="memory",
        candidate_id="candidate-2",
        report_id="report-2",
        target=target(),
        reason="high regression",
        requested_by="central",
    )

    result = executor.execute("rollback-2")

    assert result.status == "rejected"
    assert "No existe rollback handler" in (result.error or "")


def test_fails_when_handler_does_not_confirm_target(tmp_path: Path) -> None:
    executor = RollbackExecutor(tmp_path / "triade.db")
    executor.register_handler(
        "learning",
        lambda request: {
            "applied": True,
            "before_state": {"subject_id": "candidate-v2"},
            "after_state": {"subject_id": "wrong-target"},
        },
    )
    executor.plan(
        rollback_id="rollback-3",
        capability="learning",
        candidate_id="candidate-3",
        report_id="report-3",
        target=target(),
        reason="critical regression",
        requested_by="central",
    )

    result = executor.execute("rollback-3")

    assert result.status == "failed"
    assert "target_subject_id" in (result.error or "")


def test_captures_handler_exception_as_failed_audit(tmp_path: Path) -> None:
    executor = RollbackExecutor(tmp_path / "triade.db")

    def explode(request: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("restore failed")

    executor.register_handler("learning", explode)
    executor.plan(
        rollback_id="rollback-4",
        capability="learning",
        candidate_id="candidate-4",
        report_id="report-4",
        target=target(),
        reason="critical regression",
        requested_by="central",
    )

    result = executor.execute("rollback-4")

    assert result.status == "failed"
    assert result.error == "RuntimeError: restore failed"


def test_rejects_duplicate_handler_registration(tmp_path: Path) -> None:
    executor = RollbackExecutor(tmp_path / "triade.db")
    executor.register_handler("learning", lambda request: {"applied": False})

    try:
        executor.register_handler("learning", lambda request: {"applied": False})
    except ValueError as exc:
        assert "Ya existe" in str(exc)
    else:
        raise AssertionError("duplicate handler should fail")
