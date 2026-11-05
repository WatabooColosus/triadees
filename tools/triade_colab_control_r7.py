"""Tríade Ω · Centro de Control R7 para Google Colab.

Respeta el arranque R5 PIN y la recuperación V2. Permite restablecer una copia
WAL-safe más reciente SOLO si supera identidad, hash, linaje y mínimos conocidos.
El código de versiones se rehidrata desde commits inmutables de Git.
No promete continuidad de procesos cuando Colab termina el kernel.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

VERSION = "R7.4-wal-candidate"
PIN = "8fdd397b09d7c7da5da8db30235ce626d6a271ec"
REHYDRATOR_COMMIT = "ada140cf2fad8926e33843540570a1e02494c7fe"
REHYDRATOR_PATH = "tools/triade_colab_continuity_r631.py"
GUARD_TABLES = (
    "auth_users",
    "auth_email_identities",
    "neurons",
    "autonomous_tasks",
    "neuron_education_sessions",
    "neuron_education_applications",
    "metabolic_cycle",
    "worker_runs",
    "governed_research_runs",
)
REPO = "https://github.com/WatabooColosus/triadees.git"


def _check_api(url: str, timeout: float = 2.0):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, ValueError, TimeoutError):
        return False


def _read_json(path: Path):
    if not path.is_file() or path.is_symlink():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def _api_port_open():
    """An unhealthy listener must also prevent automatic memory restoration."""
    try:
        with socket.create_connection(("127.0.0.1", 8010), timeout=0.3):
            return True
    except OSError:
        return False


def _sqlite_backup(source, destination, timeout=60):
    """Copy committed SQLite state, including WAL, without unlinking sidecars.

    SQLite owns the destination transaction and rolls it back on backup error.
    Abort on a busy writer rather than waiting indefinitely or deleting locks.
    """
    deadline = time.monotonic() + timeout

    def progress(status, remaining, total):
        if status == sqlite3.SQLITE_DONE:
            return
        if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            raise RuntimeError("Bodega ocupada por otra conexión; memoria conservada")
        if time.monotonic() > deadline:
            raise RuntimeError("Tiempo de copia SQLite agotado; memoria conservada")

    with (
        contextlib.closing(
            sqlite3.connect(source.resolve().as_uri() + "?mode=ro", uri=True, timeout=0)
        ) as src,
        contextlib.closing(sqlite3.connect(destination, timeout=0)) as dst,
    ):
        src.backup(dst, pages=128, progress=progress, sleep=0.01)


def _counts(path: Path):
    if not path.is_file() or path.is_symlink():
        raise RuntimeError("Imagen de Bodega no disponible o insegura")
    with contextlib.closing(
        sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=20)
    ) as conn:
        if conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("Bodega SQLite inconsistente")
        tables = {
            r[0]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = set(GUARD_TABLES) - tables
        if missing:
            raise RuntimeError("Faltan tablas básicas: " + ",".join(sorted(missing)))
        counts = {
            t: conn.execute('SELECT COUNT(*) FROM "' + t + '"').fetchone()[0]
            for t in GUARD_TABLES
        }
        counts.update(
            {
                "neuron_activity": conn.execute(
                    "SELECT COUNT(*) FROM neuron_activity WHERE activated=1"
                ).fetchone()[0]
                if "neuron_activity" in tables
                else 0
            }
        )
        return counts


def _check_completed_study_evidence(db: Path, work: Path, drive: Path):
    """Fail closed before restoring a snapshot older than finished Drive study.

    Snapshot row counts can grow while specific study run IDs disappear. The
    Drive record is used only as a non-regression floor: it never recreates
    evaluations, upgrades session state or authenticates a training claim.
    """
    proof = _read_json(work / "restore_proof.json") or {}
    source = str(proof.get("source_sha256") or "")
    if len(source) != 64 or any(c not in "0123456789abcdef" for c in source):
        raise RuntimeError("Continuidad educativa: linaje V2 no acreditado")
    document = (
        drive
        / "operacion_colab_continua"
        / "aprendizaje"
        / source[:16]
        / "current.json"
    )
    if any(part.is_symlink() for part in (document, *document.parents)):
        raise RuntimeError("Continuidad educativa: archivo de Drive inseguro")
    if not document.is_file():
        return {"status": "no_finished_study"}
    state = _read_json(document)
    if state is None:
        raise RuntimeError("Continuidad educativa: registro de Drive inválido")
    if state.get("phase") != "done":
        return {"status": "study_not_finished"}
    session_id = state.get("session_id")
    neuron_id = state.get("neuron_id")
    if not isinstance(session_id, str) or not session_id or type(neuron_id) is not int:
        raise RuntimeError("Continuidad educativa: estudio terminado mal identificado")
    if not all(isinstance(state.get(phase), list) for phase in ("pre", "post")):
        raise RuntimeError("Continuidad educativa: pruebas terminadas inválidas")
    evidence = []
    for phase in ("pre", "post"):
        for item in state[phase]:
            run_id = item.get("run_id") if isinstance(item, dict) else None
            if not isinstance(run_id, str) or not run_id:
                raise RuntimeError(
                    "Continuidad educativa: referencia de ejecución inválida"
                )
            evidence.append((run_id, neuron_id, phase))
    if not evidence or len({x[0] for x in evidence}) != len(evidence):
        raise RuntimeError("Continuidad educativa: ejecuciones duplicadas o ausentes")
    try:
        with contextlib.closing(
            sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=20)
        ) as conn:
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if not {
                "neuron_education_sessions",
                "neuron_functional_assessments",
            }.issubset(tables):
                raise RuntimeError("Continuidad educativa: faltan tablas de evidencia")
            session = conn.execute(
                "SELECT state FROM neuron_education_sessions "
                "WHERE session_id=? AND neuron_id=?",
                (session_id, neuron_id),
            ).fetchone()
            expected = (state.get("result") or {}).get("session") or {}
            expected_state = expected.get("state")
            if session is None or session[0] == "lesson_prepared":
                raise RuntimeError(
                    "Continuidad educativa: sesión concluida retrocedida"
                    + "; session_id="
                    + session_id
                    + "; estado_db="
                    + (session[0] if session else "ausente")
                )
            if expected_state and session[0] != expected_state:
                raise RuntimeError("Continuidad educativa: estado final divergente")
            missing = [
                reference[0]
                for reference in evidence
                if conn.execute(
                    "SELECT 1 FROM neuron_functional_assessments "
                    "WHERE run_id=? AND neuron_id=? AND phase=?",
                    reference,
                ).fetchone()
                is None
            ]
    except sqlite3.Error as exc:
        raise RuntimeError("Continuidad educativa: SQLite no verificable") from exc
    if missing:
        raise RuntimeError(
            "Continuidad educativa: faltan "
            + str(len(missing))
            + " evaluaciones reales; no restaurar esta imagen"
            + "; run_ids="
            + ",".join(missing[:4])
        )
    return {"status": "finished_study_evidence_present", "runs": len(evidence)}


def _study_paths(work, drive):
    """Return paths under the verified V2 lineage, not a caller-chosen directory."""
    proof = _read_json(work / "restore_proof.json") or {}
    source = str(proof.get("source_sha256") or "")
    if len(source) != 64 or any(char not in "0123456789abcdef" for char in source):
        raise RuntimeError("Continuidad educativa: linaje V2 no acreditado")
    root = drive / "operacion_colab_continua" / "aprendizaje" / source[:16]
    original = root / "current.json"
    if any(path.is_symlink() for path in (original, *original.parents)):
        raise RuntimeError("Continuidad educativa: ruta de Drive insegura")
    return source, root, original


def _verify_fresh_epoch(db, epoch):
    """Reject a newer study whose real run IDs are absent from the selected DB."""
    if epoch.is_symlink() or any(path.is_symlink() for path in epoch.parents):
        raise RuntimeError("Continuidad educativa: nueva época con ruta insegura")
    state = _read_json(epoch)
    if state is None:
        if epoch.exists():
            raise RuntimeError("Continuidad educativa: nueva época ilegible")
        return {"status": "fresh_epoch_not_started"}
    if state.get("phase") == "done":
        backup = state.get("backup") or {}
        if not isinstance(backup, dict) or not backup.get("study_checkpoint"):
            raise RuntimeError(
                "Continuidad educativa: nueva época sin checkpoint certificado"
            )
    neuron = state.get("neuron_id")
    if type(neuron) is not int:
        raise RuntimeError("Continuidad educativa: neurona de nueva época inválida")
    refs = []
    for phase in ("pre", "post"):
        for entry in state.get(phase, []):
            run_id = entry.get("run_id") if isinstance(entry, dict) else None
            if not isinstance(run_id, str) or not run_id:
                raise RuntimeError("Continuidad educativa: ejecución nueva inválida")
            refs.append((run_id, neuron, phase))
    if len({ref[0] for ref in refs}) != len(refs):
        raise RuntimeError("Continuidad educativa: ejecución nueva duplicada")
    with contextlib.closing(
        sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=20)
    ) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if refs and "neuron_functional_assessments" not in tables:
            raise RuntimeError(
                "Continuidad educativa: faltan evaluaciones de nueva época"
            )
        for ref in refs:
            if (
                conn.execute(
                    "SELECT 1 FROM neuron_functional_assessments "
                    "WHERE run_id=? AND neuron_id=? AND phase=?",
                    ref,
                ).fetchone()
                is None
            ):
                raise RuntimeError(
                    "Continuidad educativa: nueva época retrocedida; run_id=" + ref[0]
                )
        session_id = state.get("session_id")
        if session_id:
            if "neuron_education_sessions" not in tables:
                raise RuntimeError("Continuidad educativa: sesiones nuevas ausentes")
            row = conn.execute(
                "SELECT state FROM neuron_education_sessions WHERE session_id=? "
                "AND neuron_id=?",
                (session_id, neuron),
            ).fetchone()
            if row is None:
                raise RuntimeError("Continuidad educativa: sesión nueva ausente")
            if state.get("phase") == "done":
                expected = ((state.get("result") or {}).get("session") or {}).get(
                    "state"
                )
                if not expected or row[0] != expected:
                    raise RuntimeError(
                        "Continuidad educativa: sesión nueva retrocedida"
                    )
    return {"status": "fresh_epoch_evidence_present", "runs": len(refs)}


def _legacy_quarantine_candidate(db, work, drive, review_sha):
    """Admit an unbacked 2026-era done *claim*, never a certified finished lesson.

    Strictly distinguishes a false/uncertified Drive pointer from committed
    functional data. Does not write the original pointer, database or Drive.
    """
    source, _folder, original = _study_paths(work, drive)
    if not original.is_file() or original.stat().st_size > 200_000:
        return None
    state = _read_json(original)
    backup = state.get("backup") if state else None
    result = state.get("result") if state else None
    if not (
        state.get("phase") == "done"
        and state.get("rubric_version") == "functional-probe-1"
        and str(state.get("study_id", "")).startswith("prospective-")
        and isinstance(backup, dict)
        and backup.get("status") == "encrypted_copy_verified"
        and not backup.get("study_checkpoint")
        and isinstance(result, dict)
        and (result.get("session") or {}).get("state") == "applied_neutral"
        and len(state.get("pre") or []) == 5
        and len(state.get("post") or []) == 5
    ):
        return None
    session_id = state.get("session_id")
    neuron = state.get("neuron_id")
    if not isinstance(session_id, str) or not session_id or type(neuron) is not int:
        return None
    refs = []
    for phase in ("pre", "post"):
        for entry in state[phase]:
            run_id = entry.get("run_id") if isinstance(entry, dict) else None
            if not isinstance(run_id, str) or not run_id:
                return None
            refs.append((run_id, neuron, phase))
    if len(set(refs)) != 10 or len({x[0] for x in refs}) != 10:
        return None
    with contextlib.closing(
        sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=20)
    ) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not {"neuron_functional_assessments", "neuron_education_sessions"}.issubset(
            tables
        ):
            return None
        row = conn.execute(
            "SELECT state FROM neuron_education_sessions "
            "WHERE session_id=? AND neuron_id=?",
            (session_id, neuron),
        ).fetchone()
        if not row or row[0] != "lesson_prepared":
            return None
        missing = [
            {"run_id": run_id, "phase": phase}
            for run_id, neuron_id, phase in refs
            if conn.execute(
                "SELECT 1 FROM neuron_functional_assessments "
                "WHERE run_id=? AND neuron_id=? AND phase=?",
                (run_id, neuron_id, phase),
            ).fetchone()
            is None
        ]
    # Only the specifically diagnosed final post-probe dropout qualifies.
    if len(missing) != 1 or missing[0]["phase"] != "post":
        return None
    original_hash = _sha(original)
    return {
        "schema": "triade.colab.historical_study_quarantine.v1",
        "status": "historical_claim_unverified",
        "source_sha256": source,
        "original_sha256": original_hash,
        "selected_review_sha256": review_sha,
        "session_id": session_id,
        "neuron_id": neuron,
        "actual_state": "lesson_prepared",
        "claimed_state": "applied_neutral",
        "missing_evidence": missing,
        "epoch": "recovery-" + original_hash[:16],
        "historical_certified": False,
        "historical_promotion_authorized": False,
        "original_pointer_preserved": True,
    }


def _persist_legacy_quarantine(work, drive, record):
    """Append-only evidence archive; NEVER overwrites current.json or DB."""
    source, folder, original = _study_paths(work, drive)
    if source != record["source_sha256"] or _sha(original) != record["original_sha256"]:
        raise RuntimeError("Continuidad educativa: puntero original cambió")
    root = folder / "quarantine" / record["original_sha256"]
    archive = root / "original.json"
    receipt = root / "receipt.json"
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise RuntimeError("Continuidad educativa: cuarentena insegura")
    root.mkdir(parents=True, exist_ok=True)
    data = original.read_bytes()
    if hashlib.sha256(data).hexdigest() != record["original_sha256"]:
        raise RuntimeError("Continuidad educativa: evidencia original cambió")
    for path, payload in (
        (archive, data),
        (receipt, (json.dumps(record, sort_keys=True, indent=2) + "\n").encode()),
    ):
        if path.is_file():
            if path.is_symlink() or path.read_bytes() != payload:
                raise RuntimeError("Continuidad educativa: cuarentena alterada")
            continue
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError(
                "Continuidad educativa: archivo de cuarentena en conflicto"
            ) from exc
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    if _sha(archive) != record["original_sha256"]:
        raise RuntimeError("Continuidad educativa: archivo histórico divergente")
    return receipt


def _quarantine_status(db, work, drive):
    """Only a same-lineage immutable receipt and audited restore may allow a new epoch."""
    source, folder, original = _study_paths(work, drive)
    if not original.is_file():
        return None
    digest = _sha(original)
    receipt = _read_json(folder / "quarantine" / digest / "receipt.json")
    restore = _read_json(work / "control_r7" / "last_restore.json")
    if not receipt or not restore:
        return None
    if (
        receipt.get("schema") != "triade.colab.historical_study_quarantine.v1"
        or receipt.get("status") != "historical_claim_unverified"
        or receipt.get("source_sha256") != source
        or receipt.get("original_sha256") != digest
        or not receipt.get("original_pointer_preserved")
        or receipt.get("historical_certified") is not False
        or receipt.get("historical_promotion_authorized") is not False
        or restore.get("status") != "review_restored_quarantined_history"
        or restore.get("sha256") != receipt.get("selected_review_sha256")
        or _sha(folder / "quarantine" / digest / "original.json") != digest
    ):
        return None
    if not _dominates(_counts(db), restore["counts"]):
        return None
    with contextlib.closing(
        sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=20)
    ) as conn:
        row = conn.execute(
            "SELECT state FROM neuron_education_sessions "
            "WHERE session_id=? AND neuron_id=?",
            (receipt["session_id"], receipt["neuron_id"]),
        ).fetchone()
    if row is None or row[0] != "lesson_prepared":
        return None
    epoch = folder / "epochs" / receipt["epoch"] / "current.json"
    new_study = _verify_fresh_epoch(db, epoch)
    return {
        "status": "historical_unverified_quarantined",
        "historical_certified": False,
        "historical_session": receipt["session_id"],
        "missing_evidence": receipt["missing_evidence"],
        "new_epoch": receipt["epoch"],
        "new_study": new_study,
    }


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as data:
        for block in iter(lambda: data.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _git(root, *args, timeout=150):
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError("Git: " + result.stderr.decode(errors="replace")[-400:])
    return result.stdout


def _dominates(a, b):
    return all(a.get(k, 0) >= b.get(k, 0) for k in (*GUARD_TABLES, "neuron_activity"))


class Center:
    def __init__(self, r5, rehydrator=None):
        self.r5 = r5
        self.root = Path(r5.ROOT)
        self.work = Path(r5.WORK)
        self.drive = Path(r5.BASE)
        self.db = Path(r5.DB)
        self.lock = threading.RLock()
        self.pin_sha = PIN
        self.rehydrator = rehydrator

    def _sync_paths(self):
        self.root = Path(self.r5.ROOT)
        self.work = Path(self.r5.WORK)
        self.drive = Path(self.r5.BASE)
        self.db = Path(self.r5.DB)

    def prepare_isolated_recovery(self):
        """Create an offline local fork of a verified Drive review image.

        Never alters V2, its review source, current.json, the canonical SQLite
        database, or any persistent Drive directory. No API, worker, model,
        learning pipeline, backup writer, or promotion is started.
        """
        with self.lock:
            self._sync_paths()
            if not self.drive.is_dir() or self.drive.is_symlink():
                raise RuntimeError("Drive no está montado de forma segura")
            if not self.work.is_dir() or self.work.is_symlink():
                raise RuntimeError("Directorio local de trabajo no acreditado")
            work = self.work.resolve()
            drive = self.drive.resolve()
            if work == drive or work.is_relative_to(drive):
                raise RuntimeError("Recuperación aislada nunca se escribe en Drive")
            restore_proof = _read_json(self.work / "restore_proof.json") or {}
            source_lineage = str(restore_proof.get("source_sha256") or "")
            if len(source_lineage) != 64 or any(
                character not in "0123456789abcdef" for character in source_lineage
            ):
                raise RuntimeError(
                    "Linaje verificado requerido para recuperación aislada"
                )
            self.r5.check_working_identity()
            candidate = self._checkpoint_index()
            if candidate is None:
                raise RuntimeError("No existe respaldo de revisión con SHA e identidad")
            source = candidate["file"]
            before_hash = _sha(source)
            original_hash = _sha(self.db) if self.db.is_file() else None
            study = (
                self.drive
                / "operacion_colab_continua"
                / "aprendizaje"
                / source_lineage[:16]
                / "current.json"
            )
            if any(path.is_symlink() for path in (study, *study.parents)):
                raise RuntimeError("Evidencia histórica con ruta insegura")
            evidence = _read_json(study)
            if evidence is None or evidence.get("phase") != "done":
                raise RuntimeError("Estudio finalizado de Drive no acreditado")
            session_id = evidence.get("session_id")
            neuron_id = evidence.get("neuron_id")
            if not isinstance(session_id, str) or type(neuron_id) is not int:
                raise RuntimeError("Evidencia educativa no identificable")
            references = []
            for phase in ("pre", "post"):
                records = evidence.get(phase)
                if not isinstance(records, list) or not records:
                    raise RuntimeError("Evidencia de pruebas incompleta")
                for record in records:
                    run_id = record.get("run_id") if isinstance(record, dict) else None
                    if not isinstance(run_id, str) or not run_id:
                        raise RuntimeError("Identificador de ejecución inválido")
                    references.append((run_id, phase))
            if len({run_id for run_id, _ in references}) != len(references):
                raise RuntimeError("Evidencia duplicada: no se puede bifurcar")
            # Build exclusively below the local WORK directory. Use an
            # unguessable name and never replace an earlier recovery.
            import uuid

            base = work / "isolated_recovery"
            if base.is_symlink():
                raise RuntimeError("Recuperación aislada con enlace inseguro")
            base.mkdir(mode=0o700, exist_ok=True)
            os.chmod(base, 0o700)
            destination = base / ("fork-" + uuid.uuid4().hex)
            destination.mkdir(mode=0o700)
            isolated = destination / "triade-isolated.sqlite3"
            shutil.copyfile(source, isolated, follow_symlinks=False)
            os.chmod(isolated, 0o600)
            if (
                _sha(isolated) != before_hash
                or _counts(isolated) != candidate["counts"]
                or _sha(source) != before_hash
            ):
                raise RuntimeError("La copia aislada no coincide con el respaldo")
            self.r5._owner_account_status(isolated)
            if original_hash is not None and _sha(self.db) != original_hash:
                raise RuntimeError("Base local original cambió: abortar")
            with contextlib.closing(
                sqlite3.connect(
                    isolated.resolve().as_uri() + "?mode=ro", uri=True, timeout=20
                )
            ) as connection:
                actual_session = connection.execute(
                    "SELECT state FROM neuron_education_sessions "
                    "WHERE session_id=? AND neuron_id=?",
                    (session_id, neuron_id),
                ).fetchone()
                available = {
                    (run_id, phase)
                    for run_id, phase in connection.execute(
                        "SELECT run_id,phase FROM neuron_functional_assessments "
                        "WHERE neuron_id=?",
                        (neuron_id,),
                    )
                }
            missing = [
                {"run_id": run_id, "phase": phase}
                for run_id, phase in references
                if (run_id, phase) not in available
            ]
            expected_session = (evidence.get("result") or {}).get("session") or {}
            expected_state = expected_session.get("state")
            observed_state = actual_session[0] if actual_session else None
            receipt = {
                "schema": "triade.colab.isolated_recovery.v1",
                "status": "isolated_fork_prepared",
                "original_bodega_overwritten": False,
                "drive_modified": False,
                "api_started": False,
                "workers_started": False,
                "study_promoted": False,
                "learning_authorized": False,
                "recovery_certified": False,
                "source_image": source.name,
                "source_sha256": before_hash,
                "v2_lineage_sha256": source_lineage,
                "isolated_db": str(isolated),
                "isolated_db_sha256": _sha(isolated),
                "counts": candidate["counts"],
                "historical_study": {
                    "session_id": session_id,
                    "neuron_id": neuron_id,
                    "expected_state": expected_state,
                    "observed_state": observed_state,
                    "run_refs_expected": len(references),
                    "run_refs_found": len(references) - len(missing),
                    "missing_refs": missing,
                    "status": "quarantined_unverified"
                    if missing or observed_state != expected_state
                    else "matched_but_not_cross_session_certified",
                },
                "next_step": "independent_learning_canary_only_after_sandbox_runtime_audit",
            }
            self._write_local(destination / "isolation_receipt.json", receipt)
            return receipt

    def _origin_verified(self):
        self._sync_paths()
        if not (self.root / ".git").is_dir():
            return False
        return _git(self.root, "rev-parse", "HEAD").decode().strip() == PIN and _git(
            self.root, "remote", "get-url", "origin"
        ).decode().strip() in (REPO, REPO[:-4])

    def _checkpoint_index(self):
        """Return the last *review* snapshot, never an unverified file by filename."""
        proof = _read_json(self.work / "restore_proof.json")
        if not proof or not proof.get("source_sha256"):
            return None
        base = (
            self.drive
            / "operacion_colab_r5"
            / "ramas_en_revision"
            / str(proof["source_sha256"])[:16]
        )
        pointer = _read_json(base / "latest_review.json")
        if not pointer:
            return None
        return self._validate_checkpoint(base, pointer, proof)

    def _validate_checkpoint(self, base, pointer, proof):
        filename = pointer.get("file")
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.endswith(".sqlite3")
        ):
            raise RuntimeError("Índice de respaldo con ruta insegura")
        image = base / filename
        metadata = _read_json(image.with_suffix(".json"))
        if (
            pointer.get("status") != "review_branch_only"
            or metadata != pointer
            or pointer.get("lineage") != "90e9a51dd7ffef31"
            or pointer.get("source_v2_sha256") != proof.get("source_sha256")
            or pointer.get("code_sha") != PIN
        ):
            raise RuntimeError("Respaldo no pertenece al origen certificado")
        if (
            not image.is_file()
            or image.is_symlink()
            or (Path(str(image) + "-wal").exists())
        ):
            raise RuntimeError("Imagen Drive insegura o con WAL lateral")
        if (
            len(str(pointer.get("sha256", ""))) != 64
            or _sha(image) != pointer["sha256"]
        ):
            raise RuntimeError("Huella SHA del respaldo de Drive no coincide")
        info = self.r5.db_info(image)
        if info.get("status") != "ok" or info.get("owner_fingerprint") != proof.get(
            "owner_fingerprint"
        ):
            raise RuntimeError("Identidad o SQLite inválida en respaldo de Drive")
        observed = _counts(image)
        for table, value in pointer.get("counts", {}).items():
            if observed.get(table) != value:
                raise RuntimeError(
                    "Recuento del respaldo y del manifiesto divergente: " + table
                )
        self.r5._owner_account_status(image)
        return {
            "file": image,
            "counts": observed,
            "sha256": pointer["sha256"],
            "record": pointer,
        }

    def _best_checkpoint(self, prior):
        """Inspect closed, documented snapshots of this exact V2 branch only."""
        proof = _read_json(self.work / "restore_proof.json")
        latest = self._checkpoint_index()
        candidates = [latest] if latest else []
        base = (
            self.drive
            / "operacion_colab_r5"
            / "ramas_en_revision"
            / str(proof["source_sha256"])[:16]
        )
        if base.is_dir() and not base.is_symlink():
            for metadata in sorted(base.glob("*.json")):
                if metadata.name == "latest_review.json" or metadata.is_symlink():
                    continue
                record = _read_json(metadata)
                if not record or record.get("status") != "review_branch_only":
                    continue
                try:
                    candidate = self._validate_checkpoint(base, record, proof)
                    if metadata != candidate["file"].with_suffix(".json"):
                        continue
                    candidates.append(candidate)
                except (OSError, RuntimeError, sqlite3.Error):
                    # A corrupt historical image is never a recovery source.
                    continue
        if not candidates:
            return None
        for candidate in candidates:
            if _dominates(candidate["counts"], prior) and all(
                _dominates(candidate["counts"], other["counts"]) for other in candidates
            ):
                return candidate
        raise RuntimeError(
            "Ningún respaldo supera todas las memorias verificadas; revisión manual sin cambios"
        )

    def _release_verified(self, meta):
        if not meta or meta.get("status") != "rehydrated_candidate":
            return False
        if meta.get("r631_source") != "70e17c7e3f98b162cddf98a6441830e9802e3e55":
            return False
        file = self.root / "triade/neurons/functional_evidence.py"
        expected = meta.get("verified_module_sha256")
        return bool(
            isinstance(expected, str)
            and len(expected) == 64
            and file.is_file()
            and not file.is_symlink()
            and _sha(file) == expected
        )

    def _floor(self):
        # Baseline belongs to the user's verified restoration, never to a
        # developer's historical run or synthetic test counts.
        proof = _read_json(self.work / "restore_proof.json") or {}
        floor = {
            k: v
            for k, v in proof.get("counts", {}).items()
            if k in (*GUARD_TABLES, "neuron_activity") and type(v) is int and v >= 0
        }
        source = Path(proof.get("source_path") or self.work / "absent_source")
        if source.is_file() and not source.is_symlink():
            if _sha(source) != proof.get("source_sha256"):
                raise RuntimeError("La memoria origen cambió; no omitir su protección")
            info = self.r5.db_info(source)
            if info.get("status") != "ok" or info.get("owner_fingerprint") != proof.get(
                "owner_fingerprint"
            ):
                raise RuntimeError("Identidad del origen no acreditada")
            for key, value in _counts(source).items():
                floor[key] = max(floor.get(key, 0), value)
        manifest = _read_json(self.drive / "operacion_colab_r7" / "last_success.json")
        if manifest and manifest.get("lineage") == "90e9a51dd7ffef31":
            for key, value in manifest.get("observed_counts", {}).items():
                if key in (*GUARD_TABLES, "neuron_activity") and isinstance(value, int):
                    floor[key] = max(floor.get(key, 0), value)
        return floor

    def status(self):
        self._sync_paths()
        result = {
            "panel": VERSION,
            "code_checkout": "absent",
            "kernel": "connected",
            "api_http_200": _check_api("http://127.0.0.1:8010/health/live"),
            "ollama_http_200": _check_api("http://127.0.0.1:11434/api/tags"),
            "drive_mounted": self.drive.is_dir(),
            "bodega": "absent",
            "release": "R5 (sin superposición certificada)",
            "guardian": "not_certified",
        }
        try:
            if self._origin_verified():
                result["code_checkout"] = "R5 pinned " + PIN[:12]
        except (OSError, RuntimeError):
            result["code_checkout"] = "conflicto de commit/origen"
        if self.db.is_file():
            try:
                counts = _counts(self.db)
                self.r5._owner_account_status(self.db)
                result.update(bodega="SQLite ok / propietario validado", counts=counts)
                missing = {
                    k: v for k, v in self._floor().items() if counts.get(k, 0) < v
                }
                result["known_regression"] = missing or None
            except (RuntimeError, sqlite3.Error) as ex:
                result["bodega"] = "BLOQUEADA: " + str(ex)[:150]
        meta = _read_json(self.work / "actualizaciones" / "continuidad_git_r631.json")
        if self._release_verified(meta):
            result["release"] = (
                "R6.3.1 candidata / Git " + str(meta.get("r631_source", ""))[:10]
            )
        elif meta:
            result["release"] = "R6.3.1 registrada, código local SIN VERIFICAR"
        else:
            for tag in ("r63_active.json", "r62_active.json"):
                st = _read_json(self.work / "actualizaciones" / tag)
                if st and st.get("status") == "active_candidate":
                    result["release"] = (
                        "R6.3 candidata" if "r63" in tag else "R6.2 candidata"
                    )
                    break
        guardian = _read_json(self.work / "r5_guardian.json")
        if guardian:
            result["guardian"] = (
                "PID registrado "
                + str(guardian.get("pid", "sin ID"))
                + " (actividad no comprobada)"
            )
        if self.drive.is_dir():
            try:
                v2 = _read_json(
                    self.drive / "continuidad_runtime" / "v2" / "active_verified.json"
                )
                result["drive_v2_image"] = v2.get("file") if v2 else "índice ausente"
                record = (
                    self._checkpoint_index()
                    if (self.work / "restore_proof.json").exists()
                    else None
                )
                result["drive_last_guarded_backup"] = (
                    record["file"].name if record else "no comprobado"
                )
            except (RuntimeError, sqlite3.Error) as ex:
                result["drive_last_guarded_backup"] = "error: " + str(ex)[:160]
        # A successful SQLite check alone does not prove that completed
        # education runs survived a restart. Distinguish a quarantined legacy
        # claim from a certified completed historical education session.
        if (
            self.db.is_file()
            and self.drive.is_dir()
            and (self.work / "restore_proof.json").is_file()
        ):
            try:
                result["education_continuity"] = _check_completed_study_evidence(
                    self.db, self.work, self.drive
                )
            except (OSError, RuntimeError, sqlite3.Error) as exc:
                try:
                    quarantined = _quarantine_status(self.db, self.work, self.drive)
                except (OSError, RuntimeError, sqlite3.Error, ValueError, KeyError):
                    quarantined = None
                result["education_continuity"] = quarantined or {
                    "status": "regressed_blocked",
                    "reason": str(exc)[:300],
                }
        return result

    def resume_verified(self, baseline):
        """Warm cell reload checks local runtime; does not rehash Drive images."""
        self._sync_paths()
        if not isinstance(baseline, dict) or not all(
            k in baseline for k in GUARD_TABLES
        ):
            return False
        if not _check_api("http://127.0.0.1:8010/health/live") or not _check_api(
            "http://127.0.0.1:11434/api/tags"
        ):
            return False
        if not self._origin_verified() or not self._release_verified(
            _read_json(self.work / "actualizaciones" / "continuidad_git_r631.json")
        ):
            return False
        self.r5._owner_account_status(self.db)
        return _dominates(_counts(self.db), baseline)

    def _restore_best_before_api(self):
        """Replace only the just-restored V2 local copy, with a strictly verifiable later image."""
        self._sync_paths()
        if _check_api("http://127.0.0.1:8010/health/live") or _api_port_open():
            raise RuntimeError("API activa: nunca sustituir Bodega viva")
        proof = _read_json(self.work / "restore_proof.json")
        if not proof:
            raise RuntimeError("R5 aún no acreditó restauración; sin cambios")
        self.r5.check_working_identity()
        prior = _counts(self.db)
        review = self._best_checkpoint(prior)
        chosen = None
        if review is not None:
            if not _dominates(review["counts"], prior):
                raise RuntimeError(
                    "Respaldo de revisión no supera al V2 en todas las tablas; revisión manual"
                )
            if any(
                review["counts"][x] > prior[x]
                for x in (*GUARD_TABLES, "neuron_activity")
            ):
                chosen = review
        if chosen is None:
            failures = {k: n for k, n in self._floor().items() if prior.get(k, 0) < n}
            if failures:
                raise RuntimeError(
                    "V2 retrocede y no hay copia revisada más reciente acreditada: "
                    + str(failures)
                )
            _check_completed_study_evidence(self.db, self.work, self.drive)
            return {
                "result": "V2 local validada y suficiente; no se reemplazó",
                "counts": prior,
            }
        current = chosen["counts"]
        failures = {k: n for k, n in self._floor().items() if current.get(k, 0) < n}
        if failures:
            raise RuntimeError(
                "La copia Drive más reciente sigue siendo antigua: " + str(failures)
            )
        # Check each completed run and terminal session before touching the live
        # SQLite destination. Count-dominant images can still omit committed work.
        historical_quarantine = None
        try:
            _check_completed_study_evidence(chosen["file"], self.work, self.drive)
        except RuntimeError:
            # A *legacy uncertified pointer* can be archived and superseded,
            # not certified. This applies to no valid completed checkpoint.
            # Do not discard a real finished study in the local V2 image.
            try:
                _check_completed_study_evidence(self.db, self.work, self.drive)
            except RuntimeError:
                historical_quarantine = _legacy_quarantine_candidate(
                    chosen["file"], self.work, self.drive, chosen["sha256"]
                )
            if historical_quarantine is None:
                raise
        if historical_quarantine is not None:
            _source, folder, _ = _study_paths(self.work, self.drive)
            _verify_fresh_epoch(
                chosen["file"],
                folder / "epochs" / historical_quarantine["epoch"] / "current.json",
            )
        # WAL/SHM presence alone is normal, including after read-only checks.
        # Let SQLite preserve committed WAL state and restore transactionally;
        # never replace the database inode underneath existing sidecars/readers.
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S%fZ")
        vault = self.work / "control_r7" / "before_review_restore" / stamp
        vault.mkdir(parents=True, exist_ok=False)
        backup = vault / "v2_pre_restore.sqlite3"
        _sqlite_backup(self.db, backup)
        if _counts(backup) != prior:
            raise RuntimeError("Backup local previo incompleto; DB original conservada")
        staged = vault / "review_staged.sqlite3"
        shutil.copy2(chosen["file"], staged)
        if _sha(staged) != chosen["sha256"] or _counts(staged) != current:
            raise RuntimeError("SHA o recuentos de imagen staged divergentes")
        self.r5._owner_account_status(staged)
        if _api_port_open() or _counts(self.db) != prior:
            raise RuntimeError("La Bodega cambió durante la preparación; sin restaurar")
        _sqlite_backup(staged, self.db)
        if _counts(self.db) != current:
            raise RuntimeError("Imagen restaurada no coincide; no arrancar API")
        self.r5.check_working_identity()
        if historical_quarantine is not None:
            _persist_legacy_quarantine(self.work, self.drive, historical_quarantine)
        receipt = {
            "status": (
                "review_restored_quarantined_history"
                if historical_quarantine is not None
                else "review_restored_validated"
            ),
            "historical_education_certified": historical_quarantine is None,
            "file": chosen["file"].name,
            "sha256": chosen["sha256"],
            "backup_original": str(backup),
            "restore_method": "sqlite_backup_transaction",
            "counts": current,
        }
        self._write_local(self.work / "control_r7" / "last_restore.json", receipt)
        if historical_quarantine is not None:
            receipt["education_continuity"] = _quarantine_status(
                self.db, self.work, self.drive
            )
            if receipt["education_continuity"] is None:
                raise RuntimeError("Restauración pendiente: cuarentena no acreditada")
        return receipt

    @staticmethod
    def _write_local(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".partial")
        if tmp.exists() or tmp.is_symlink():
            raise RuntimeError("Archivo temporal anterior en conflicto: " + str(tmp))
        tmp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp, path)

    def start(self):
        """Start from R5 verified Drive, upgrade to pinned code, leave workers owned by backend."""
        with self.lock:
            self._sync_paths()
            if _check_api("http://127.0.0.1:8010/health/live"):
                current = self.status()
                if current.get("bodega", "").startswith("BLOQUEADA"):
                    raise RuntimeError(
                        "API viva con Bodega no acreditada: intervención manual"
                    )
                updated = (
                    self.install_release()
                    if "R6.3.1" not in current.get("release", "")
                    else {"state": "already_installed"}
                )
                guardian = self.r5.start_guardian()
                return {
                    "state": "already_running_verified",
                    "release": updated,
                    "guardian": guardian,
                    "status": self.status(),
                }
            self.r5.install_first()
            self._sync_paths()
            self.r5.connect_verified_v2()
            reviewed = self._restore_best_before_api()
            self.r5.model_ready()
            self.r5.start_real_backend()
            if not _check_api("http://127.0.0.1:8010/health/live"):
                raise RuntimeError("La API R5 no confirmó HTTP 200")
            receipt = self.install_release()
            if (
                receipt.get("state") not in ("already_installed",)
                and receipt.get("status") != "rehydrated_candidate"
            ):
                raise RuntimeError(
                    "No se acreditó la versión restaurada; conservar registros para revisar"
                )
            guardian = self.r5.start_guardian()
            return {
                "state": "running_version_rehydrated",
                "restore": reviewed,
                "release": receipt,
                "guardian": guardian,
                "status": self.status(),
            }

    def install_release(self):
        """Only R6.3.1 audited immutable chain; never change V2 or install moving main."""
        with self.lock:
            if not self._origin_verified():
                raise RuntimeError("No hay checkout R5 oficial. Arranca R5 primero.")
            if not _check_api("http://127.0.0.1:8010/health/live"):
                raise RuntimeError("Arranca primero la API autenticada R5")
            counts = _counts(self.db)
            missing = {k: v for k, v in self._floor().items() if counts.get(k, 0) < v}
            if missing:
                raise RuntimeError(
                    "Memoria retrocedida. No actualizar: " + str(missing)
                )
            existing = _read_json(
                self.work / "actualizaciones" / "continuidad_git_r631.json"
            )
            if existing and existing.get("status") == "rehydrated_candidate":
                if not self._release_verified(existing):
                    raise RuntimeError(
                        "La versión registrada y el código no coinciden; no se declara instalada"
                    )
                return {"state": "already_installed", "status": self.status()}
            if self.rehydrator is not None:
                receipt = self.rehydrator(self.r5, minimum_counts=self._floor())
                if (
                    receipt.get("status") != "rehydrated_candidate"
                    or receipt.get("api_http") != 200
                ):
                    raise RuntimeError("Versión candidata no acreditada")
                return receipt
            _git(
                self.root,
                "fetch",
                "--no-tags",
                "--depth",
                "1",
                "origin",
                REHYDRATOR_COMMIT,
            )
            if (
                _git(self.root, "rev-parse", "FETCH_HEAD").decode().strip()
                != REHYDRATOR_COMMIT
            ):
                raise RuntimeError("La versión Git no coincide con el commit fijado")
            source = _git(self.root, "show", REHYDRATOR_COMMIT + ":" + REHYDRATOR_PATH)
            if not 0 < len(source) < 200000:
                raise RuntimeError("Fuente de versión inválida")
            import ast
            import types

            module = types.ModuleType("triade_colab_continuity_r631")
            exec(  # noqa: S102 - pinned audited Git commit
                compile(
                    ast.parse(source.decode("utf-8"), filename=REHYDRATOR_PATH),
                    REHYDRATOR_PATH,
                    "exec",
                ),
                module.__dict__,
            )
            receipt = module.rehydrate(self.r5)
            if (
                receipt.get("status") != "rehydrated_candidate"
                or receipt.get("api_http") != 200
            ):
                raise RuntimeError("Versión candidata no acreditada")
            return receipt

    def check_updates(self):
        """Consult Git only; do not install a moving ref or equate main with candidate."""
        with self.lock:
            self._sync_paths()
            if not (self.root / ".git").is_dir():
                return {
                    "installed": "Ningún checkout; inicia primero",
                    "target_pinned": "R6.3.1",
                    "remote_main": None,
                }
            fetched = (
                _git(self.root, "ls-remote", "origin", "refs/heads/main")
                .decode()
                .strip()
            )
            remote_sha = fetched.split()[0] if fetched else None
            state = self.status()
            return {
                "installed": state["release"],
                "target_pinned": "R6.3.1 candidata",
                "release_source_commit": REHYDRATOR_COMMIT,
                "remote_main": remote_sha,
                "note": "main puede contener una versión distinta; no se aplica sin nueva auditoría",
            }

    def save(self):
        with self.lock:
            if not self.drive.is_dir():
                raise RuntimeError("Drive desconectado, no hay respaldo persistente")
            # Never make a new review checkpoint from an already-regressed DB.
            _check_completed_study_evidence(self.db, self.work, self.drive)
            result = self.r5.save_review_copy()
            if not result or result.get("status") not in (
                "saved_review_only",
                "quota",
                "too_soon",
            ):
                raise RuntimeError("Guardián no confirmó escritura: " + str(result))
            return {"guardian": result, "status": self.status()}

    def start_guardian(self):
        with self.lock:
            return self.r5.start_guardian()

    def record_release(self):
        """Manifest is an observation, not a substitute for an actual snapshot."""
        with self.lock:
            if not self.drive.is_dir() or not self.db.is_file():
                raise RuntimeError("Sin Drive o Bodega")
            proof = _read_json(self.work / "restore_proof.json")
            if not proof or not self._origin_verified():
                raise RuntimeError("Sin identidad/checkout R5 acreditados")
            self.r5._owner_account_status(self.db)
            _check_completed_study_evidence(self.db, self.work, self.drive)
            review = self._checkpoint_index()
            if not review:
                raise RuntimeError(
                    "No hay imagen de Drive comprobada; no marcar continuidad"
                )
            _check_completed_study_evidence(review["file"], self.work, self.drive)
            # La memoria viva puede avanzar durante el guardado. Certificamos la imagen
            # restaurable en Drive, no afirmamos que tenga todos los ciclos presentes.
            manifest = {
                "schema": "triade_r7_operational_checkpoint_v1",
                "lineage": "90e9a51dd7ffef31",
                "release": self.status()["release"],
                "r5_commit": PIN,
                "observed_counts": review["counts"],
                "snapshot_sha256": review["sha256"],
                "snapshot_file": review["file"].name,
                "written_at": dt.datetime.now(dt.UTC).isoformat(),
            }
            self._write_local(
                self.drive / "operacion_colab_r7" / "last_success.json", manifest
            )
            return manifest


def render(r5):
    from html import escape

    import ipywidgets as w
    from IPython.display import HTML, clear_output, display

    center = Center(r5)
    display(
        HTML("""<style>.r7hero{background:linear-gradient(120deg,#071b37,#162354 53%,#38134d);padding:22px;border-radius:18px;border:1px solid #3f8fdd;color:#f0f8ff;font:15px system-ui}
.r7hero h2{color:#6df2ef;margin:0 0 10px}.r7hero small{color:#b1cef0}.r7pill{display:inline-block;border:1px solid #648dc3;border-radius:100px;padding:6px 10px;margin:5px;color:#d4ebff}</style>""")
    )
    display(
        HTML(
            """<div class="r7hero"><h2>TRÍADE Ω · CENTRO DE CONTINUIDAD R7</h2><small>Git = código · Drive = memoria · Colab = ejecución temporal</small><div><span class="r7pill">Versión verificable</span><span class="r7pill">Identidad protegida</span><span class="r7pill">Reinicio seguro</span><span class="r7pill">Sin procesos duplicados</span></div></div>"""
        )
    )
    info = w.HTML(value="<b>Centro autónomo: Encender / actualizar y Abrir Tríade.</b>")
    out = w.Output(
        layout=w.Layout(
            border="1px solid #426aac",
            max_height="460px",
            overflow="auto",
            padding="10px",
        )
    )
    busy = w.HTML("")

    def execute(label, fn):
        with out:
            clear_output(wait=True)
            print("TRÍADE Ω ·", label)
            try:
                result = fn()
                print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
                print("✓ Operación concluida. Verifica el resultado real en la salida.")
            except (
                OSError,
                RuntimeError,
                ValueError,
                sqlite3.Error,
                subprocess.SubprocessError,
            ) as exc:
                print("✗ Operación no acreditada:", type(exc).__name__, str(exc)[:1400])
            info.value = "<b>Panel consultado:</b> " + escape(
                dt.datetime.now().strftime("%H:%M:%S")
            )
            busy.value = ""

    def button(label, fn, color=""):
        b = w.Button(
            description=label,
            button_style=color,
            layout=w.Layout(width="275px", height="41px"),
        )

        def click(_):
            if busy.value:
                return
            busy.value = "<b>Ejecutando acción. Evita pulsar otro botón.</b>"
            execute(label, fn)

        b.on_click(click)
        return b

    def open_verified_frontend():
        observed = center.status()
        if not (
            observed.get("api_http_200") is True
            and observed.get("ollama_http_200") is True
            and str(observed.get("bodega", "")).startswith("SQLite ok")
            and observed.get("known_regression") is None
            and str(observed.get("release", "")).startswith("R6.3.1 candidata")
            and (observed.get("education_continuity") or {}).get("status")
            != "regressed_blocked"
        ):
            raise RuntimeError(
                "Abrir Tríade requiere API, Ollama, Bodega y continuidad "
                "acreditadas; consulta Estado real"
            )
        r5.open_frontend()
        return {"status": "frontend_requested"}

    controls = [
        button("Instalar / encender / actualizar", center.start, "success"),
        button("Abrir Tríade", open_verified_frontend, "info"),
    ]
    display(
        info,
        busy,
        w.Box(
            controls, layout=w.Layout(display="flex", flex_flow="row wrap", gap="8px")
        ),
        w.HTML(
            "<small>La supervisión, memoria y aprendizaje pertenecen al ciclo "
            "gobernado de Tríade. Este panel no sustituye el índice V2.</small>"
        ),
        out,
    )
    return center
