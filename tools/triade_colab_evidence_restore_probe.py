"""Independent, non-destructive restoration proof using an authentic worker receipt.

Restores into a disposable filesystem root; never passes the live runtime or
SQLite path to the restore routine. It cannot authorize A/B promotion.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def prove_isolated_restore(
    agent: Any, store_dir: Path, *, temp_base: Path
) -> dict[str, Any]:
    """Verify archive, restore, idempotence and corruption refusal in isolation.

    Never removes an original artifact. Temporary trees live outside Drive.
    """
    store = Path(store_dir)
    temp_base = Path(temp_base)
    if store.is_symlink() or not store.is_dir():
        raise RuntimeError("unsafe_archive_store")
    if temp_base.is_symlink() or not temp_base.is_dir():
        raise RuntimeError("unsafe_temporary_root")
    if temp_base.resolve().is_relative_to(
        store.resolve()
    ) or store.resolve().is_relative_to(temp_base.resolve()):
        raise RuntimeError("isolation_boundary_invalid")
    items = store / "items"
    if items.is_symlink() or not items.is_dir():
        raise RuntimeError("archive_items_not_available")

    selected: tuple[Path, Path, dict[str, bytes]] | None = None
    for prefix in sorted(items.iterdir()):
        if prefix.is_symlink() or not prefix.is_dir():
            continue
        for record in sorted(prefix.iterdir()):
            verified = agent._verify_store(record)
            if verified is not None:
                relative, files = verified
                selected = record, relative, files
                break
        if selected is not None:
            break
    if selected is None:
        raise RuntimeError("no_valid_canonical_receipt")

    record, relative, files = selected
    digest = _sha(relative.as_posix().encode("utf-8"))
    with tempfile.TemporaryDirectory(
        prefix="triade-proof-", dir=str(temp_base)
    ) as folder:
        isolation = Path(folder)
        sandbox_store = isolation / "archive"
        copy_target = sandbox_store / "items" / digest[:2] / digest
        copy_target.parent.mkdir(parents=True)
        shutil.copytree(record, copy_target, symlinks=True)
        if agent._verify_store(copy_target) is None:
            raise RuntimeError("archive_copy_failed_sha_verification")

        clean_runtime = isolation / "runtime"
        clean_runtime.mkdir()
        first = agent.restore(clean_runtime, sandbox_store, max_items=1)
        if first.get("restored") != 1 or first.get("conflicts") != 0:
            raise RuntimeError("isolated_restore_not_verified")
        restored_dir = clean_runtime / relative.parent
        for name, raw in files.items():
            if (restored_dir / name).is_symlink() or (
                restored_dir / name
            ).read_bytes() != raw:
                raise RuntimeError("restored_file_bytes_mismatch")

        second = agent.restore(clean_runtime, sandbox_store, max_items=1)
        if second.get("restored") != 0 or second.get("already_present") != 1:
            raise RuntimeError("restore_idempotence_failed")
        # Corrupt only the disposable archive COPY, not any real Drive receipt.
        (copy_target / "result.json").write_bytes(b'{"altered":true}')
        tampered_runtime = isolation / "tampered_runtime"
        tampered_runtime.mkdir()
        rejected = agent.restore(tampered_runtime, sandbox_store, max_items=1)
        if rejected.get("restored") != 0 or rejected.get("invalid_receipts") != 1:
            raise RuntimeError("tampering_was_not_rejected")
        if (tampered_runtime / relative).exists():
            raise RuntimeError("invalid_receipt_restored_anyway")

    return {
        "schema": "triade.colab.evidence.isolated_restore.v1",
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "source": "authentic_sha_verified_receipt_in_private_drive",
        "source_ref_sha256": digest,
        "verified_file_count": len(files),
        "restore": first,
        "repeat_restore": second,
        "tamper_rejection": rejected,
        "bytes_identical": True,
        "isolation": "disposable_colab_temp_directory_outside_runtime_and_drive",
        "live_runtime_modified": False,
        "stable_memory_written": False,
        "promotion_authorized": False,
        "colab_restart_restoration_certified": False,
    }


def proof_json(report: dict[str, Any]) -> bytes:
    return (
        json.dumps(report, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode("utf-8")
