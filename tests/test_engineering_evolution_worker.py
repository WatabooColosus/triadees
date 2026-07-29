from pathlib import Path

import pytest

from triade.evolution.engineering_worker import (
    EngineeringEvolutionWorker,
    EvolutionBudget,
)


def test_protected_paths_and_file_budget():
    with pytest.raises(ValueError, match="protected_path"):
        EngineeringEvolutionWorker._validate_files(
            ["triade/memory/schemas.sql"], EvolutionBudget()
        )
    with pytest.raises(ValueError, match="protected_path"):
        EngineeringEvolutionWorker._validate_files(
            ["tests/test_gate.py"], EvolutionBudget()
        )
    with pytest.raises(ValueError, match="file_budget"):
        EngineeringEvolutionWorker._validate_files(
            [f"triade/x{i}.py" for i in range(13)], EvolutionBudget()
        )


def test_independent_review_never_accepts_failed_candidate():
    review = EngineeringEvolutionWorker._review(
        {"passed": True}, {"passed": False}, ["triade/x.py"]
    )
    assert review["decision"] == "reject_candidate"
    assert review["independent_tests"] is True


def test_commit_requires_named_approval(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    worker = EngineeringEvolutionWorker(repo, tmp_path / "db.sqlite")
    assert worker.approve_and_commit("missing", approved_by="")["status"] == "blocked"
