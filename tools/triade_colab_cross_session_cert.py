"""Cross-session evidence restore attestation, separate from any A/B promotion.

Writes immutable session anchors in private Drive; never deletes or edits worker
receipts, runtime task results or the SQLite Bodega. No background execution.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

HEX = re.compile(r"[a-f0-9]{32}\Z")
FORMAT = "triade.worker.evidence.cross_session.v1"
MAX_ANCHORS = 32
MAX_SESSION_MARKERS = 500


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(obj: dict) -> bytes:
    return (
        json.dumps(obj, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    ).encode()


def runtime_identity(sentinel: Path) -> str:
    """Persistent for the *current ephemeral Colab filesystem*, not Drive.

    An OS kernel restart on the same /content does not count as a new session.
    """
    if sentinel.is_symlink() or any(p.is_symlink() for p in sentinel.parents):
        raise RuntimeError("unsafe_runtime_identity_path")
    if sentinel.exists():
        if not sentinel.is_file() or sentinel.stat().st_size > 256:
            raise RuntimeError("invalid_runtime_identity_file")
        value = sentinel.read_text().strip()
        if not HEX.fullmatch(value):
            raise RuntimeError("invalid_runtime_identity")
        return value
    if not sentinel.parent.is_dir():
        raise RuntimeError("missing_runtime_identity_parent")
    value = uuid4().hex
    try:
        fd = os.open(sentinel, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return runtime_identity(sentinel)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(value + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    return value


def _valid_archive(
    agent: Any, store: Path, relative_ref: str
) -> tuple[str, dict[str, bytes]] | None:
    relative = Path(relative_ref)
    # _relative on the actual runtime root is checked before materializing.
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.name != "result.json"
    ):
        return None
    if relative.parts[:2] != ("runs", "background"):
        return None
    record = agent._archive_dir(store, relative)
    verified = agent._verify_store(record)
    if verified is None or verified[0] != relative:
        return None
    _ref, data = verified
    return _sha(data["manifest.json"]), data


def _anchors(agent: Any, store: Path) -> list[dict[str, str]]:
    items = store / "items"
    if not items.is_dir() or items.is_symlink():
        return []
    anchors: list[dict[str, str]] = []
    for prefix in sorted(items.iterdir()):
        if (
            prefix.is_symlink()
            or not prefix.is_dir()
            or not re.fullmatch(r"[a-f0-9]{2}", prefix.name)
        ):
            continue
        for record in sorted(prefix.iterdir()):
            verified = agent._verify_store(record)
            if verified is None:
                continue
            relative, files = verified
            anchors.append(
                {
                    "result_ref": relative.as_posix(),
                    "manifest_sha256": _sha(files["manifest.json"]),
                    "result_sha256": _sha(files["result.json"]),
                }
            )
            if len(anchors) >= MAX_ANCHORS:
                return anchors
    return anchors


def _previous_marker(agent: Any, store: Path, session_id: str) -> dict | None:
    records = store / "session_certification" / "anchors"
    if not records.exists():
        return None
    if not records.is_dir() or records.is_symlink():
        raise RuntimeError("unsafe_anchor_archive")
    candidates = []
    for child in records.iterdir():
        if (
            child.is_symlink()
            or not child.is_file()
            or not re.fullmatch(r"session-[a-f0-9]{32}\.json", child.name)
        ):
            continue
        if child.stat().st_size > 16384:
            continue
        candidates.append(child)
    if len(candidates) > MAX_SESSION_MARKERS:
        raise RuntimeError("too_many_session_markers_manual_review")
    for item in sorted(candidates, key=lambda p: p.stat().st_mtime_ns, reverse=True):
        try:
            obj = json.loads(item.read_bytes())
            if obj.get("schema") != FORMAT or obj.get("session_id") == session_id:
                continue
            if item.name != "session-" + str(obj["session_id"]) + ".json":
                continue
            vals = obj.get("anchors")
            if not isinstance(vals, list) or not (1 <= len(vals) <= MAX_ANCHORS):
                continue
            found = []
            for x in vals:
                if not isinstance(x, dict) or not all(
                    isinstance(x.get(k), str)
                    for k in ("result_ref", "manifest_sha256", "result_sha256")
                ):
                    continue
                v = _valid_archive(agent, store, x["result_ref"])
                if (
                    v is None
                    or v[0] != x["manifest_sha256"]
                    or _sha(v[1]["result.json"]) != x["result_sha256"]
                ):
                    continue
                found.append(x)
            if found:
                return {"session_id": obj["session_id"], "anchors": found}
        except (OSError, ValueError, KeyError, TypeError, RuntimeError):
            continue
    return None


def prepare(agent: Any, runtime_root: Path, store_dir: Path, session_id: str) -> dict:
    """Call BEFORE automatic restoration; record which prior receipts were absent."""
    root = agent._safe_base(Path(runtime_root))
    store = agent._safe_base(Path(store_dir))
    if not HEX.fullmatch(session_id):
        raise RuntimeError("invalid_session_identity")
    old = _previous_marker(agent, store, session_id)
    missing: list[str] = []
    if old:
        for a in old["anchors"]:
            relative = agent._relative(root, a["result_ref"])
            if relative is not None and not (root / relative.parent).exists():
                missing.append(a["result_ref"])
    return {
        "prior_session": old["session_id"] if old else None,
        "prior_anchors_verified": len(old["anchors"]) if old else 0,
        "prior_refs_missing_before_restore": missing,
    }


def complete(
    agent: Any,
    runtime_root: Path,
    store_dir: Path,
    session_id: str,
    before: dict,
    restored: dict,
) -> dict:
    """Call AFTER restoration; report only proven cross-session recovery."""
    root = agent._safe_base(Path(runtime_root))
    store = agent._safe_base(Path(store_dir))
    if not HEX.fullmatch(session_id):
        raise RuntimeError("invalid_session_identity")
    verified_recovered = []
    for ref in before.get("prior_refs_missing_before_restore", []):
        relative = agent._relative(root, ref)
        if relative is None:
            continue
        saved = _valid_archive(agent, store, ref)
        existing = agent._read_and_verify(root, relative)
        if saved is not None and existing is not None and saved[1] == existing[1]:
            verified_recovered.append(_sha(ref.encode()))
    previous = before.get("prior_session")
    actual_restored = (
        restored.get("restored", 0) if restored.get("status") == "ok" else 0
    )
    certified = bool(
        previous
        and previous != session_id
        and actual_restored > 0
        and verified_recovered
    )
    new_anchors = _anchors(agent, store)
    anchors_dir = store / "session_certification" / "anchors"
    for p in (store / "session_certification", anchors_dir):
        if p.is_symlink():
            raise RuntimeError("symlink_session_record")
        p.mkdir(exist_ok=True)
    marker = anchors_dir / ("session-" + session_id + ".json")
    if marker.is_symlink():
        raise RuntimeError("symlink_session_marker")
    baseline = {
        "schema": FORMAT,
        "session_id": session_id,
        "created_at": dt.datetime.now(dt.UTC).isoformat(),
        "anchors": new_anchors,
        "production_modified": False,
        "promotion_authorized": False,
    }
    if not marker.exists() and new_anchors:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(_json(baseline))
            stream.flush()
            os.fsync(stream.fileno())
    elif marker.exists() and (not marker.is_file() or marker.stat().st_size > 16384):
        raise RuntimeError("invalid_existing_session_marker")
    return {
        "schema": "triade.colab.cross_session_attestation.v1",
        "status": "cross_session_verified"
        if certified
        else (
            "same_session_or_no_prior_baseline"
            if not previous
            else "unverified_recovery"
        ),
        "previous_session": previous is not None and previous != session_id,
        "prior_anchors_verified": before.get("prior_anchors_verified", 0),
        "prior_refs_missing_before_restore": len(
            before.get("prior_refs_missing_before_restore", [])
        ),
        "restored_by_runtime": actual_restored,
        "verified_recovered_refs": len(verified_recovered),
        "anchor_saved": marker.is_file(),
        "anchor_count": len(new_anchors),
        "cross_session_restoration_certified": certified,
        "live_runtime_modified_by_certifier": False,
        "memory_modified": False,
        "promotion_authorized": False,
        "canary_certified": False,
    }
