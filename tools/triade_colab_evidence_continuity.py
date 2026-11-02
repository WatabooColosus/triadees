"""Append-only continuity for genuine canonical worker task artifacts in Colab.

Not an A/B gate: never changes SQLite, produces incidents or promotes candidates.
The user's private mounted Drive holds immutable, SHA-256-verified receipts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
from pathlib import Path
from uuid import uuid4

FORMAT = "triade.worker.artifact.archive.v1"
TERMINAL = frozenset(
    (
        "completed",
        "observed",
        "cancelled",
        "blocked",
        "failed",
        "dead_letter",
        "timeout",
        "lease_lost",
    )
)
HEX64 = re.compile(r"^[a-f0-9]{64}$")
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_RECEIPT_BYTES = 6 * 1024 * 1024
MAX_MANIFEST_BYTES = 128 * 1024
ARCHIVE_LIMIT = 128
SCAN_LIMIT = 10000
_LOCK = threading.Lock()


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_base(path: Path) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise RuntimeError("unsafe_root")
    resolved = path.resolve(strict=True)
    if path != resolved and any(x.is_symlink() for x in [path, *path.parents]):
        raise RuntimeError("symlink_root")
    return resolved


def _relative(root: Path, value: str) -> Path | None:
    """No traversal, symlinks, or paths outside designated runtime root."""
    ref = Path(value)
    if not value or ".." in ref.parts or ref.name != "result.json":
        return None
    try:
        if ref.is_absolute():
            relative = ref.relative_to(root)
        else:
            relative = ref
        if not relative.parts or relative.parts[:2] != ("runs", "background"):
            return None
        # Don't permit alternative or hidden path components.
        if any(p in (".", "..", "") or p.startswith(".") for p in relative.parts):
            return None
        dest = root
        for part in relative.parts:
            dest /= part
            if dest.is_symlink():
                return None
        if not dest.resolve(strict=False).is_relative_to(root):
            return None
        return relative
    except (ValueError, OSError, RuntimeError):
        return None


def _read_and_verify(
    root: Path, relative: Path, row: tuple | None = None
) -> tuple[dict, dict[str, bytes]] | None:
    """Require full canonical manifest, not just a detached result.json."""
    directory = root / relative.parent
    manifest_file = directory / "manifest.json"
    if (
        manifest_file.is_symlink()
        or not manifest_file.is_file()
        or manifest_file.stat().st_size > MAX_MANIFEST_BYTES
    ):
        return None
    try:
        manifest_bytes = manifest_file.read_bytes()
        manifest = json.loads(manifest_bytes)
        hashes = manifest.get("artifact_hashes")
        if not isinstance(hashes, dict) or "result.json" not in hashes:
            return None
        if (
            not isinstance(manifest.get("result_hash"), str)
            or manifest["result_hash"] != hashes["result.json"]
        ):
            return None
        if row is not None:
            task_id, task_type, status, worker_id, lease_generation = row
            if any(
                (manifest.get(k) != value)
                for k, value in (
                    ("task_id", task_id),
                    ("task_type", task_type),
                    ("status", status),
                    ("worker_id", worker_id),
                    ("lease_generation", lease_generation),
                )
            ):
                return None
        if len(hashes) > 24:
            return None
        data = {"manifest.json": manifest_bytes}
        total = len(manifest_bytes)
        for name, sha in hashes.items():
            if (
                not isinstance(name, str)
                or name in ("", ".", "..", "manifest.json")
                or Path(name).name != name
                or name.startswith(".")
            ):
                return None
            if not isinstance(sha, str) or not HEX64.fullmatch(sha):
                return None
            file = directory / name
            if file.is_symlink() or not file.is_file():
                return None
            if file.stat().st_size > MAX_FILE_BYTES:
                return None
            raw = file.read_bytes()
            if _hash(raw) != sha:
                return None
            total += len(raw)
            if total > MAX_RECEIPT_BYTES:
                return None
            data[name] = raw
        if not isinstance(json.loads(data["result.json"]), dict):
            return None
        return manifest, data
    except (OSError, ValueError, KeyError, TypeError, UnicodeError, sqlite3.Error):
        return None


def _receipt(relative: Path, data: dict[str, bytes]) -> bytes:
    body = {
        "schema": FORMAT,
        "relative_result_ref": relative.as_posix(),
        "files": {name: _hash(raw) for name, raw in sorted(data.items())},
    }
    return (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _safe_private_directory(base: Path, relative: Path) -> Path:
    current = base
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise RuntimeError("symlink_directory_rejected")
        current.mkdir(exist_ok=True)
    return current


def _archive_dir(store: Path, relative: Path) -> Path:
    digest = _hash(relative.as_posix().encode())
    return store / "items" / digest[:2] / digest


def _verify_store(path: Path) -> tuple[Path, dict[str, bytes]] | None:
    if path.is_symlink() or not path.is_dir():
        return None
    receipt = path / "receipt.json"
    if (
        receipt.is_symlink()
        or not receipt.is_file()
        or receipt.stat().st_size > MAX_MANIFEST_BYTES
    ):
        return None
    try:
        metadata = json.loads(receipt.read_bytes())
        if metadata.get("schema") != FORMAT:
            return None
        ref = metadata["relative_result_ref"]
        relative = Path(ref)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.parts[:2] != ("runs", "background")
            or relative.name != "result.json"
        ):
            return None
        if _archive_dir(path.parents[2], relative) != path:
            return None
        hashes = metadata["files"]
        if (
            not isinstance(hashes, dict)
            or "manifest.json" not in hashes
            or "result.json" not in hashes
            or len(hashes) > 25
        ):
            return None
        data = {}
        total = 0
        for name, digest in hashes.items():
            if (
                Path(name).name != name
                or name.startswith(".")
                or not HEX64.fullmatch(digest)
            ):
                return None
            f = path / name
            if f.is_symlink() or not f.is_file() or f.stat().st_size > MAX_FILE_BYTES:
                return None
            b = f.read_bytes()
            total += len(b)
            if total > MAX_RECEIPT_BYTES or _hash(b) != digest:
                return None
            data[name] = b
        manifest = json.loads(data["manifest.json"])
        if not isinstance(manifest, dict) or manifest.get("artifact_hashes") != {
            k: v for k, v in hashes.items() if k != "manifest.json"
        }:
            return None
        if manifest.get("result_hash") != hashes["result.json"]:
            return None
        if not isinstance(json.loads(data["result.json"]), dict):
            return None
        return relative, data
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        return None


def archive(
    db_path: str | Path,
    runtime_root: str | Path,
    store_dir: str | Path,
    *,
    max_new: int = ARCHIVE_LIMIT,
) -> dict:
    """Read-only SQLite scan; only copy authentic complete receipts to Drive."""
    if not _LOCK.acquire(blocking=False):
        return {"status": "busy", "archived": 0}
    try:
        root = _safe_base(Path(runtime_root))
        store = _safe_base(Path(store_dir))
        db = Path(db_path)
        if db.is_symlink() or not db.is_file():
            raise RuntimeError("unsafe_database_source")
        counts = {
            "examined": 0,
            "archived": 0,
            "already_archived": 0,
            "unavailable_or_invalid": 0,
            "conflicts": 0,
        }
        with sqlite3.connect(f"file:{db.resolve()}?mode=ro", uri=True) as conn:
            rows = conn.execute(
                "SELECT task_id, task_type, status, worker_id, lease_generation, result_ref "
                "FROM autonomous_tasks WHERE result_ref IS NOT NULL AND status IN ("
                + ",".join("?" for _ in TERMINAL)
                + ") "
                "ORDER BY updated_at DESC LIMIT ?",
                (*sorted(TERMINAL), SCAN_LIMIT),
            )
            for task_id, task_type, status, worker_id, generation, reference in rows:
                counts["examined"] += 1
                relative = _relative(root, str(reference or ""))
                if relative is None:
                    counts["unavailable_or_invalid"] += 1
                    continue
                target = _archive_dir(store, relative)
                if target.exists() or target.is_symlink():
                    verified = _verify_store(target)
                    if verified is not None and verified[0] == relative:
                        counts["already_archived"] += 1
                    else:
                        counts["conflicts"] += 1
                    continue
                if counts["archived"] >= max_new:
                    break
                candidate = _read_and_verify(
                    root, relative, (task_id, task_type, status, worker_id, generation)
                )
                if candidate is None:
                    counts["unavailable_or_invalid"] += 1
                    continue
                _, data = candidate
                parent = _safe_private_directory(
                    store, Path("items") / _hash(relative.as_posix().encode())[:2]
                )
                temp = parent / (".staging-" + uuid4().hex)
                temp.mkdir(mode=0o700)
                try:
                    for name, raw in data.items():
                        (temp / name).write_bytes(raw)
                    (temp / "receipt.json").write_bytes(_receipt(relative, data))
                    # Verify the staged contents BEFORE publishing.
                    # Verification uses target's canonical identity, so compare content hashes here.
                    if any(
                        _hash((temp / name).read_bytes()) != _hash(raw)
                        for name, raw in data.items()
                    ):
                        raise RuntimeError("staging_hash_mismatch")
                    if target.exists() or target.is_symlink():
                        counts["conflicts"] += 1
                        continue
                    os.rename(temp, target)
                    if _verify_store(target) is None:
                        raise RuntimeError("published_receipt_verification_failed")
                    counts["archived"] += 1
                finally:
                    if temp.exists():
                        import shutil

                        shutil.rmtree(temp)
        return {"status": "ok", "memory_modified": False, **counts}
    finally:
        _LOCK.release()


def restore(
    runtime_root: str | Path, store_dir: str | Path, *, max_items: int = 10000
) -> dict:
    """Restore missing entire directories; never overwrite any existing file."""
    if not _LOCK.acquire(blocking=False):
        return {"status": "busy", "restored": 0}
    try:
        root = _safe_base(Path(runtime_root))
        store = _safe_base(Path(store_dir))
        counts = {
            "restored": 0,
            "already_present": 0,
            "conflicts": 0,
            "invalid_receipts": 0,
        }
        items = store / "items"
        if not items.exists():
            return {"status": "ok", "memory_modified": False, **counts}
        if items.is_symlink() or not items.is_dir():
            raise RuntimeError("unsafe_archive_items")
        for prefix in sorted(items.iterdir()):
            if (
                prefix.is_symlink()
                or not prefix.is_dir()
                or not re.fullmatch(r"[0-9a-f]{2}", prefix.name)
            ):
                counts["invalid_receipts"] += 1
                continue
            for record in sorted(prefix.iterdir()):
                if sum(counts.values()) >= max_items:
                    break
                verified = _verify_store(record)
                if verified is None:
                    counts["invalid_receipts"] += 1
                    continue
                relative, data = verified
                if _relative(root, relative.as_posix()) is None:
                    counts["conflicts"] += 1
                    continue
                target_dir = root / relative.parent
                if target_dir.exists() or target_dir.is_symlink():
                    # Partial/conflicting directories are never silently patched.
                    present = _read_and_verify(root, relative)
                    if (
                        present is not None
                        and set(present[1]) == set(data)
                        and all(present[1][k] == b for k, b in data.items())
                    ):
                        counts["already_present"] += 1
                    else:
                        counts["conflicts"] += 1
                    continue
                parent = _safe_private_directory(root, relative.parent.parent)
                temp = parent / (".restore-" + uuid4().hex)
                temp.mkdir(mode=0o700)
                try:
                    for name, raw in data.items():
                        (temp / name).write_bytes(raw)
                    if target_dir.exists() or target_dir.is_symlink():
                        counts["conflicts"] += 1
                        continue
                    os.rename(temp, target_dir)
                    if _read_and_verify(root, relative) is None:
                        raise RuntimeError("restored_receipt_verification_failed")
                    counts["restored"] += 1
                finally:
                    if temp.exists():
                        import shutil

                        shutil.rmtree(temp)
        return {"status": "ok", "memory_modified": False, **counts}
    finally:
        _LOCK.release()
