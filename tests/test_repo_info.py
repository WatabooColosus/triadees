"""Tests de informacion Git expuesta a la web."""

from __future__ import annotations

from triade.core import repo_info as repo_info_module
from triade.core.repo_info import _canonical_origin, repo_info


def test_repo_info_reports_connected_origin() -> None:
    info = repo_info()

    assert info["status"] == "ok"
    assert info["origin"] == "https://github.com/WatabooColosus/triadees.git"
    assert info["branch"]
    assert info["commit"]
    assert "dirty" in info


def test_canonical_origin_accepts_github_checkout_url_without_git_suffix() -> None:
    assert _canonical_origin("https://github.com/WatabooColosus/triadees") == "https://github.com/WatabooColosus/triadees.git"


def test_repo_info_uses_github_head_ref_when_checkout_is_detached(monkeypatch) -> None:
    def fake_git(args: list[str], _cwd) -> str:
        if args == ["remote", "get-url", "origin"]:
            return "https://github.com/WatabooColosus/triadees"
        if args == ["rev-parse", "--short", "HEAD"]:
            return "abc1234"
        return ""

    monkeypatch.setattr(repo_info_module, "_git", fake_git)
    monkeypatch.setenv("GITHUB_HEAD_REF", "codex/auditoria-evolutiva-triade")

    info = repo_info()

    assert info["origin"] == "https://github.com/WatabooColosus/triadees.git"
    assert info["branch"] == "codex/auditoria-evolutiva-triade"
