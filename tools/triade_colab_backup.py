"""Colab backup continuity, separate from canonical V2 memory and legacy keys.

Never restores a DB, removes a backup, rotates an existing key, starts a service,
or changes autonomy. New Colab protection has its own persistent key namespace.
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import sqlite3
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from triade.security.file_privacy import protect_private_file


def _read(path):
    try:
        value = json.loads(path.read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _plain_file(path):
    return not any(p.is_symlink() for p in (path, *path.parents))


def _key(path):
    if not _plain_file(path):
        raise RuntimeError("backup_path_symlink_blocked")
    if not path.is_file():
        return None
    with path.open("rb") as stream:
        raw = stream.read(257).strip()
    if len(raw) != 44:
        raise RuntimeError("backup_key_invalid_preserved")
    try:
        Fernet(raw)
    except (ValueError, TypeError) as exc:
        raise RuntimeError("backup_key_invalid_preserved") from exc
    return raw


def _fingerprint(raw):
    return hashlib.sha256(b"triade-backup-key:" + raw).hexdigest()[:16]


def _private_new(path, data):
    if not _plain_file(path):
        raise RuntimeError("backup_path_symlink_blocked")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        if path.read_bytes() != data:
            raise RuntimeError("backup_file_conflict_preserved") from None
        return
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    protect_private_file(path)


def _json(path, value):
    if not _plain_file(path):
        raise RuntimeError("backup_path_symlink_blocked")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    _private_new(temp, (json.dumps(value, indent=2) + "\n").encode())
    os.replace(temp, path)


def _backend_environment(r5):
    from tools.colab_service_lifecycle import process_owned

    record_path = Path(r5.WORK) / "api_ownership.json"
    if not process_owned(Path(r5.ROOT), record_path):
        raise RuntimeError("backend_ownership_not_verified")
    pid = int(_read(record_path)["pid"])
    entries = (Path("/proc") / str(pid) / "environ").read_bytes().split(b"\0")
    env = dict(entry.split(b"=", 1) for entry in entries if b"=" in entry)
    return {
        key: env.get(key.encode(), b"").decode()
        for key in ("TRIADE_BACKUP_KEY", "TRIADE_BACKUP_KEY_FILE")
    }


def provision(r5, persistent):
    """Recover a unique existing key or provision a NEW Colab-only domain."""
    backend = _backend_environment(r5)
    paths = [persistent / "backup.key"]
    prior = _read(persistent / "status.json")
    prior_fp = str(prior.get("key_fingerprint", ""))
    if len(prior_fp) == 16 and all(c in "0123456789abcdef" for c in prior_fp):
        paths.append(Path(r5.WORK) / "private_backup_keys" / (prior_fp + ".key"))
    for root in (Path(r5.ROOT), Path(r5.BASE)):
        location = _read(root / "config" / "backup_key_location.json")
        if location.get("key_file"):
            paths.append(Path(location["key_file"]).expanduser())
    paths.extend(
        Path(r5.BASE) / name
        for name in (
            "seguridad/backup.key",
            "config/backup.key",
            "backup.key",
            "triade_backup.key",
        )
    )
    if backend.get("TRIADE_BACKUP_KEY_FILE"):
        paths.append(Path(backend["TRIADE_BACKUP_KEY_FILE"]).expanduser())
    candidates = {}
    for path in paths:
        raw = _key(path)
        if raw is not None:
            candidates[_fingerprint(raw)] = raw
    inline = backend.get("TRIADE_BACKUP_KEY", "").strip().encode()
    if inline:
        Fernet(inline)
        candidates[_fingerprint(inline)] = inline
    if len(candidates) > 1:
        raise RuntimeError("multiple_backup_keys_preserved_manual_selection_required")
    existed = bool(candidates)
    if not existed and (
        prior
        or any((persistent / "copies").glob("*.fernet"))
        or any((Path(r5.ROOT) / "artifacts" / "backups").glob("*.fernet"))
    ):
        raise RuntimeError("existing_encrypted_backups_require_original_key")
    raw = next(iter(candidates.values())) if existed else Fernet.generate_key()
    if prior_fp and prior_fp != _fingerprint(raw):
        raise RuntimeError("persistent_backup_key_identity_conflict")
    local_copies = sorted(
        (Path(r5.ROOT) / "artifacts" / "backups").glob("*.fernet"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if local_copies:
        if not _plain_file(local_copies[0]):
            raise RuntimeError("backup_path_symlink_blocked")
        try:
            # Verify the existing corpus's latest authentication tag BEFORE
            # activating a recovered key; never silently change its domain.
            Fernet(raw).extract_timestamp(local_copies[0].read_bytes())
        except (InvalidToken, ValueError) as exc:
            raise RuntimeError(
                "existing_encrypted_backup_key_mismatch_preserved"
            ) from exc
    # Existing persistent key files are never overwritten, including invalid ones.
    _private_new(persistent / "backup.key", raw)
    if _key(persistent / "backup.key") != raw:
        raise RuntimeError("persistent_backup_key_verification_failed")
    fp = _fingerprint(raw)
    local = Path(r5.WORK) / "private_backup_keys" / (fp + ".key")
    _private_new(local, raw)
    local.chmod(0o600)
    if os.name != "nt" and local.stat().st_mode & 0o077:
        raise RuntimeError("local_backup_key_not_private")
    return (
        local,
        fp,
        (
            "existing_key_recovered"
            if existed
            else "new_colab_domain_legacy_key_not_recovered"
        ),
    )


def _backup_instance(r5):
    from triade.memory.encrypted_backup import EncryptedBackup

    # Avoid __init__'s migration writes: only SQLite online backup and its
    # normal integrity/decryption checks are needed here.
    backup = object.__new__(EncryptedBackup)
    backup.db_path = Path(r5.DB)
    backup.backup_dir = Path(r5.ROOT) / "artifacts" / "backups"
    backup.backup_dir.mkdir(parents=True, exist_ok=True)
    backup.minimum_interval_seconds = 300
    backup.require_identity_manifest = False
    return backup


def _persist(backup, file, persistent, fp):
    manifest_path = file.with_suffix(file.suffix + ".json")
    if not _plain_file(file) or not _plain_file(manifest_path):
        raise RuntimeError("backup_path_symlink_blocked")
    manifest = _read(manifest_path)
    if manifest.get("key_fingerprint") != fp:
        raise RuntimeError("backup_fingerprint_mismatch_preserved")
    verified = backup.verify(file)
    if verified.get("status") != "ok":
        raise RuntimeError("backup_roundtrip_verification_failed")
    destination = persistent / "copies"
    for path in (file, manifest_path):
        _private_new(destination / path.name, path.read_bytes())
        if (
            hashlib.sha256((destination / path.name).read_bytes()).digest()
            != hashlib.sha256(path.read_bytes()).digest()
        ):
            raise RuntimeError("persistent_backup_copy_verification_failed")
    return {
        "file": file.name,
        "sha256": manifest["sha256"],
        "integrity": "ok",
        "decryption_verified": True,
        "drive_copy_verified": True,
        "key_fingerprint": fp,
        "saved_at": time.time(),
    }


def _verify_archived_study(backup, file, study):
    """Confirm the encrypted checkpoint retains real pre/post rows and terminal state.

    Never infer missing rows from the study JSON. Restore only to a temporary
    isolated database and reject any mismatch before publishing a Drive receipt.
    """
    if study.get("phase") != "checkpoint_pending":
        raise RuntimeError("prospective_checkpoint_not_pending")
    session_id = study.get("session_id")
    neuron_id = study.get("neuron_id")
    expected_session = (study.get("result") or {}).get("session") or {}
    expected_state = expected_session.get("state")
    if (
        not isinstance(session_id, str)
        or not session_id
        or type(neuron_id) is not int
        or not isinstance(expected_state, str)
        or not expected_state
        or expected_state == "lesson_prepared"
    ):
        raise RuntimeError("prospective_checkpoint_invalid_session")
    run_proofs = []
    for phase in ("pre", "post"):
        cases = study.get(phase)
        if not isinstance(cases, list) or not cases:
            raise RuntimeError("prospective_checkpoint_invalid_cases")
        for proof in cases:
            if not isinstance(proof, dict):
                raise TypeError("prospective_checkpoint_invalid_cases")
            run_id, case_id, score = (
                proof.get("run_id"),
                proof.get("case_id"),
                proof.get("score"),
            )
            if (
                not isinstance(run_id, str)
                or not run_id
                or not isinstance(case_id, str)
                or type(score) not in (float, int)
            ):
                raise RuntimeError("prospective_checkpoint_invalid_cases")
            run_proofs.append((run_id, phase, case_id, float(score)))
    if len({run_id for run_id, _, _, _ in run_proofs}) != len(run_proofs):
        raise RuntimeError("prospective_checkpoint_duplicate_run")
    with tempfile.TemporaryDirectory(prefix="triade-study-proof-") as directory:
        extracted = Path(directory) / "restored-checkpoint.sqlite3"
        result = backup.restore_to_sandbox(file, extracted)
        if result.get("status") != "restored_sandbox" or result.get(
            "production_overwritten"
        ):
            raise RuntimeError("prospective_checkpoint_restore_unverified")
        conn = sqlite3.connect(extracted.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            row = conn.execute(
                "SELECT state,post_score FROM neuron_education_sessions "
                "WHERE session_id=? AND neuron_id=?",
                (session_id, neuron_id),
            ).fetchone()
            if row is None or row[0] != expected_state:
                raise RuntimeError("prospective_checkpoint_session_mismatch")
            measured_post = expected_session.get("post_score")
            if measured_post is not None and (
                row[1] is None or abs(float(row[1]) - float(measured_post)) > 1e-6
            ):
                raise RuntimeError("prospective_checkpoint_session_score_mismatch")
            for run_id, phase, case_id, score in run_proofs:
                found = conn.execute(
                    "SELECT phase,case_id,score,session_id "
                    "FROM neuron_functional_assessments "
                    "WHERE run_id=? AND neuron_id=?",
                    (run_id, neuron_id),
                ).fetchone()
                if (
                    found is None
                    or found[0] != phase
                    or found[1] != case_id
                    or found[2] is None
                    or abs(float(found[2]) - score) > 1e-6
                    or (phase == "post" and found[3] != session_id)
                ):
                    raise RuntimeError(
                        "prospective_checkpoint_run_missing_or_mismatched"
                    )
        finally:
            conn.rollback()
            conn.close()
    return {
        "verified_run_count": len(run_proofs),
        "study_id": str(study.get("study_id") or ""),
        "session_id": session_id,
        "runs_sha256": hashlib.sha256(
            "\n".join(sorted(item[0] for item in run_proofs)).encode()
        ).hexdigest(),
    }


def _paths(r5):
    proof = _read(Path(r5.WORK) / "restore_proof.json")
    source = str(proof.get("source_sha256", ""))
    if len(source) != 64 or any(c not in "0123456789abcdef" for c in source):
        raise RuntimeError("verified_memory_source_required_for_backup")
    persistent = (
        Path(r5.BASE) / "operacion_colab_continua" / "proteccion_cifrada" / source[:16]
    )
    if not Path(r5.BASE).is_dir() or not _plain_file(persistent):
        raise RuntimeError("mounted_drive_required_for_backup")
    return persistent


def _serialized(fn):
    @functools.wraps(fn)
    def call(r5, **kwargs):
        path = Path(r5.WORK) / "encrypted_backup.lock"
        if not _plain_file(path):
            raise RuntimeError("backup_path_symlink_blocked")
        with path.open("a") as stream:
            if os.name == "nt":
                import msvcrt

                stream.seek(0)
                stream.write("0")
                stream.flush()
                msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    return fn(r5, **kwargs)
                finally:
                    try:
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
                return fn(r5, **kwargs)

    return call


@_serialized
def repair(r5, *, require_fresh=False, study_state=None):
    """One legitimate backup, tested in temporary storage; never DB restore.

    A completed prospective study cannot reuse a prior cooldown backup.
    """
    if require_fresh and not isinstance(study_state, dict):
        raise RuntimeError("fresh_study_proof_required")
    r5._owner_account_status(r5.DB)
    persistent = _paths(r5)
    local, fp, resolution = provision(r5, persistent)
    location = Path(r5.ROOT) / "config" / "backup_key_location.json"
    if location.exists():
        original = location.read_bytes()
        _private_new(
            Path(r5.WORK)
            / "backup_config_history"
            / (hashlib.sha256(original).hexdigest() + ".json"),
            original,
        )
    # MissionPlanner rereads this canonical pointer each cycle. No restart or
    # mutation of the other process's environment is performed.
    _json(
        location,
        {"key_file": str(local), "key_fingerprint": fp, "scope": "colab_protection"},
    )
    os.environ["TRIADE_BACKUP_KEY_FILE"] = str(local)
    os.environ.pop("TRIADE_BACKUP_KEY", None)
    backup = _backup_instance(r5)
    created = backup.create(force=require_fresh)
    if created.get("status") == "completed":
        file = backup.backup_dir / created["file"]
    elif (
        not require_fresh
        and created.get("status") == "blocked"
        and created.get("reason") == "backup_cooldown_active"
    ):
        file = Path(created["latest"])
        if _read(file.with_suffix(file.suffix + ".json")).get("key_fingerprint") != fp:
            created = backup.create(force=True)
            if created.get("status") != "completed":
                raise RuntimeError("new_domain_backup_creation_not_verified")
            file = backup.backup_dir / created["file"]
    else:
        raise RuntimeError("fresh_backup_creation_not_verified")
    study_proof = (
        _verify_archived_study(backup, file, study_state) if require_fresh else None
    )
    receipt = {
        "status": "encrypted_copy_verified",
        "key_resolution": resolution,
        "legacy_encrypted_backups_recovery": "not_certified",
        **_persist(backup, file, persistent, fp),
        "study_checkpoint": study_proof,
        "backend_key_activation": "await_next_planner_cycle",
    }
    _json(persistent / "status.json", receipt)
    _json(Path(r5.WORK) / "encrypted_backup_status.json", receipt)
    return receipt


@_serialized
def replicate(r5):
    """Copy at most two new real encrypted backups per day, never delete files."""
    persistent = _paths(r5)
    receipt = _read(persistent / "status.json")
    fp = receipt.get("key_fingerprint")
    files = sorted(
        (Path(r5.ROOT) / "artifacts" / "backups").glob("triade-*.db.gz.fernet"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    eligible = [
        file
        for file in files
        if _read(file.with_suffix(file.suffix + ".json")).get("key_fingerprint") == fp
    ]
    if not eligible or eligible[0].name == receipt.get("file"):
        return receipt
    today = time.strftime("%Y-%m-%d", time.gmtime())
    history = _read(persistent / "copy_budget.json")
    count = history.get("count", 0) if history.get("day") == today else 0
    if count >= 2:
        return {"status": "deferred_daily_copy_limit"}
    receipt.update(_persist(_backup_instance(r5), eligible[0], persistent, fp))
    _json(persistent / "status.json", receipt)
    _json(persistent / "copy_budget.json", {"day": today, "count": count + 1})
    _json(Path(r5.WORK) / "encrypted_backup_status.json", receipt)
    return receipt


def start_watch(r5):
    previous = getattr(r5, "_encrypted_backup_watch", None)
    if previous:
        previous["stop"].set()
        previous["thread"].join(timeout=1)
        if previous["thread"].is_alive():
            raise RuntimeError("previous_backup_copy_still_running")
    stop = threading.Event()

    def watch():
        while not stop.wait(600):
            try:
                replicate(r5)
            except Exception as exc:  # noqa: BLE001 - preserve loop, report without secrets
                _json(
                    Path(r5.WORK) / "encrypted_backup_copy_error.json",
                    {
                        "status": "copy_failed",
                        "error_type": type(exc).__name__,
                        "at": time.time(),
                    },
                )

    thread = threading.Thread(target=watch, name="triade-encrypted-copy", daemon=True)
    r5._encrypted_backup_watch = {"stop": stop, "thread": thread}
    thread.start()


def status(r5):
    result = _read(Path(r5.WORK) / "encrypted_backup_status.json")
    result["copy_receipt_kind"] = "last_verified_copy"
    if isinstance(result.get("saved_at"), (int, float)):
        result["copy_age_seconds"] = max(0, time.time() - result["saved_at"])
    # Public health returns the backend's actual key resolution. Filter its
    # broader response; never return key paths, emails or authentication data.
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8010/api/health", timeout=8
        ) as response:
            data = json.loads(response.read(1_000_001))
        key = data.get("security", {}).get("backup_key", {})
        result["backend_key"] = {
            name: key.get(name)
            for name in ("configured", "source", "path_exists", "path_readable")
        }
        result["backend_key_activation"] = (
            "configured_observed"
            if key.get("configured") is True
            else "not_configured_observed"
            if key.get("configured") is False
            else "not_observed"
        )
    except (OSError, ValueError, TypeError, AttributeError):
        result["backend_key"] = {"status": "not_observed"}
        result["backend_key_activation"] = "not_observed"
    watcher = getattr(r5, "_encrypted_backup_watch", None)
    result["copy_watcher_alive"] = bool(
        watcher and watcher["thread"].is_alive() and not watcher["stop"].is_set()
    )
    result["last_copy_error"] = (
        _read(Path(r5.WORK) / "encrypted_backup_copy_error.json") or None
    )
    return result
