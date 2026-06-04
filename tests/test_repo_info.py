"""Tests de informacion Git expuesta a la web."""

from __future__ import annotations

from triade.core.repo_info import repo_info


def test_repo_info_reports_connected_origin() -> None:
    info = repo_info()

    assert info["status"] == "ok"
    assert info["origin"] == "https://github.com/WatabooColosus/triadees.git"
    assert info["branch"]
    assert info["commit"]
    assert "dirty" in info
