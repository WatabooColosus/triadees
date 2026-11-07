"""Package contract for Colab backup/worker health fixes.

All test paths are tmp_path fixtures; production Drive and SQLite are untouched.
"""

from __future__ import annotations

import contextlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import colab_service_lifecycle
from tools import triade_colab_release as adapter

_REPO = Path(__file__).resolve().parents[1]
_MODULES = {
    "backup_key_resolution": "triade/memory/encrypted_backup.py",
    "service_health_progress": "triade/runtime/service_health.py",
}


def test_pinned_colab_sources_match_corrected_runtime_modules() -> None:
    """Keep immutable release snapshots byte-identical to the corrected source."""
    for name, actual in _MODULES.items():
        source = _REPO / "tools/colab_patch_sources" / (name + ".py")
        assert source.is_file()
        assert source.read_bytes() == (_REPO / actual).read_bytes()


def _fixture(tmp_path: Path):
    root = tmp_path / "repo"
    work = tmp_path / "work"
    root.mkdir()
    work.mkdir()
    files = {}
    for name, actual in _MODULES.items():
        destination = root / actual
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text("# original pinned runtime", encoding="utf-8")
        files[name] = str(
            _REPO / "tools/colab_patch_sources" / (name + ".py")
        )
    calls: list[str] = []
    r5 = SimpleNamespace(
        ROOT=root,
        WORK=work,
        start_real_backend=lambda: calls.append("restart"),
    )
    return {"r5": r5, "files": files, "progress": lambda _: None}, calls


def test_release_patches_two_modules_and_verifies_without_touching_bodega(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarded code restart, backup originals, never open SQLite or Drive."""
    context, calls = _fixture(tmp_path)
    monkeypatch.setattr(
        adapter,
        "_center",
        lambda context: SimpleNamespace(_origin_verified=lambda: True),
    )
    monkeypatch.setattr(
        colab_service_lifecycle,
        "stop_owned",
        lambda root, ownership, port: calls.append("stop"),
    )
    monkeypatch.setattr(
        adapter.urllib.request,
        "urlopen",
        lambda url, timeout: contextlib.nullcontext(SimpleNamespace(status=200)),
    )

    assert adapter._runtime_patches_match(context) is True
    result = adapter._apply_runtime_path_patches(context)
    context["require_runtime_patch_verification"] = True

    assert result["status"] == "patched_and_restarted"
    assert calls == ["stop", "restart"]
    assert adapter._runtime_patches_match(context) is True
    assert not list((tmp_path / "repo").rglob("*.db"))
    for name, actual in _MODULES.items():
        assert (tmp_path / "repo" / actual).read_bytes() == Path(
            context["files"][name]
        ).read_bytes()
    previous = list((tmp_path / "work" / "actualizaciones" / "runtime_path_patches").rglob("encrypted_backup.py"))
    assert len(previous) == 1
    assert previous[0].read_text(encoding="utf-8") == "# original pinned runtime"


def test_corrupted_patch_rejected_without_stopping_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context, calls = _fixture(tmp_path)
    context["files"]["backup_key_resolution"] = str(tmp_path / "absent.py")
    monkeypatch.setattr(
        colab_service_lifecycle,
        "stop_owned",
        lambda root, ownership, port: calls.append("stop"),
    )

    with pytest.raises(RuntimeError, match="Componente de runtime ausente"):
        adapter._apply_runtime_path_patches(context)
    assert calls == []


def test_release_receipt_cannot_verify_unapplied_code(
    tmp_path: Path,
) -> None:
    context, _ = _fixture(tmp_path)
    context["require_runtime_patch_verification"] = True
    assert adapter._runtime_patches_match(context) is False
