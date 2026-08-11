"""Backup SQLite cifrado y restauración comprobada (opt-in por clave)."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from triade.db import sqlite3


class EncryptedBackup:
    def __init__(
        self,
        db_path: str | Path = "triade/memory/triade.db",
        backup_dir: str | Path = "artifacts/backups",
        minimum_interval_seconds: int = 300,
        require_identity_manifest: bool = False,
    ) -> None:
        self.db_path, self.backup_dir = Path(db_path), Path(backup_dir)
        self.minimum_interval_seconds = max(0, minimum_interval_seconds)
        self.require_identity_manifest = require_identity_manifest
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        migration = (
            Path(__file__).resolve().parent / "migrations/031_restore_drills.sql"
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(migration.read_text(encoding="utf-8"))

    @staticmethod
    def ensure_key_file_mode() -> dict[str, Any]:
        """Cierra los permisos de la clave antes de arrancar, y dice si tuvo que hacerlo.

        `_fernet()` exige `0600` y aborta si el fichero deja algo a grupo u otros.
        La exigencia es correcta, pero deja al organismo sin backups en cuanto
        algo externo abre el modo — y eso pasa: el filesystem del Studio devuelve
        `0744` a todo en cada reinicio. El 2026-08-08 costó trece horas sin una
        sola copia, con cada `encrypted_backup` cayendo en `dead_letter`.

        Cerrar el modo no borra la exposición que ya ocurrió, así que esto **no
        silencia el detector**: devuelve `tightened` con el modo anterior para que
        el arranque lo diga en voz alta. Lo que evita es que una protección que ya
        está configurada deje de aplicarse por un permiso que nadie miró.
        """
        key_file = os.getenv("TRIADE_BACKUP_KEY_FILE", "").strip()
        if not key_file:
            return {"status": "absent", "reason": "sin TRIADE_BACKUP_KEY_FILE"}
        path = Path(key_file)
        try:
            before = path.stat().st_mode & 0o777
        except OSError as exc:
            return {"status": "unreadable", "path": str(path), "reason": str(exc)}
        if not before & 0o077:
            return {"status": "ok", "path": str(path), "mode": f"{before:04o}"}
        try:
            path.chmod(0o600)
        except OSError as exc:
            return {
                "status": "failed",
                "path": str(path),
                "mode_before": f"{before:04o}",
                "reason": str(exc),
            }
        return {
            "status": "tightened",
            "path": str(path),
            "mode_before": f"{before:04o}",
            "mode_after": "0600",
        }

    @staticmethod
    def _integrity_of(db_path: Path) -> str:
        """Lo que dice SQLite de una base, o por qué no se pudo preguntar.

        Devuelve texto siempre —nunca lanza— porque quien llama necesita poder
        decidir sin envolverlo en otro `try`: una base tan dañada que ni se abre
        es exactamente el caso que hay que detectar, no una excepción a ignorar.
        """
        try:
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
                return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        except sqlite3.Error as exc:
            return f"unreadable: {exc}"

    @staticmethod
    def _fernet():
        from cryptography.fernet import Fernet

        key_text = os.getenv("TRIADE_BACKUP_KEY", "").strip()
        key_file = os.getenv("TRIADE_BACKUP_KEY_FILE", "").strip()
        if not key_text and key_file:
            path = Path(key_file)
            mode = path.stat().st_mode & 0o777
            if mode & 0o077:
                raise PermissionError("backup_key_file_permissions_must_be_0600")
            key_text = path.read_text(encoding="utf-8").strip()
        key = key_text.encode()
        if not key:
            raise RuntimeError(
                "TRIADE_BACKUP_KEY o TRIADE_BACKUP_KEY_FILE requerida; "
                "no se crean backups sin cifrado"
            )
        return Fernet(key)

    @staticmethod
    def key_fingerprint() -> str | None:
        """Huella de la clave activa, o `None` si no hay ninguna.

        Los manifiestos guardaban el hash del cifrado y el de la base original,
        pero **nada que identificara la clave**. Con varias claves a mano —o con
        una rotación— no había forma de saber cuál abre cuál: sólo probar. Y un
        backup que no se sabe abrir no es un backup.

        Es un SHA-256 truncado con prefijo de dominio: sirve para comparar dos
        claves, nunca para reconstruir una.
        """
        key_text = os.getenv("TRIADE_BACKUP_KEY", "").strip()
        key_file = os.getenv("TRIADE_BACKUP_KEY_FILE", "").strip()
        if not key_text and key_file:
            try:
                key_text = Path(key_file).read_text(encoding="utf-8").strip()
            except OSError:
                return None
        if not key_text:
            return None
        digest = hashlib.sha256(b"triade-backup-key:" + key_text.encode()).hexdigest()
        return digest[:16]

    def create(self, *, force: bool = False) -> dict[str, Any]:
        recent = sorted(
            self.backup_dir.glob("triade-*.db.gz.fernet"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if (
            recent
            and not force
            and time.time() - recent[0].stat().st_mtime < self.minimum_interval_seconds
        ):
            return {
                "status": "blocked",
                "reason": "backup_cooldown_active",
                "latest": str(recent[0]),
            }
        with tempfile.TemporaryDirectory(prefix="triade-backup-") as directory:
            snapshot = Path(directory) / "snapshot.db"
            with (
                sqlite3.connect(self.db_path) as source,
                sqlite3.connect(snapshot) as target,
            ):
                source.backup(target)
            # Copiar sin mirar es archivar el daño. El 2026-08-08 la base de
            # producción se corrompió entre dos copias; la siguiente se creó a
            # partir de ella y se guardó como si estuviera bien. Nadie lo supo
            # hasta que hizo falta restaurar, y para entonces la copia más
            # reciente —la que cualquiera habría elegido— era inservible.
            #
            # Si hubiera tardado unas horas más en notarse, las nueve copias
            # buenas habrían rotado hasta desaparecer. Un backup que archiva
            # corrupción es peor que no tenerlo: aparenta protección y además
            # **desplaza** a las copias que sí servían.
            #
            # Se comprueba sobre el snapshot, antes de comprimir y cifrar, para
            # que una base dañada no llegue a escribirse nunca.
            integridad = self._integrity_of(snapshot)
            if integridad != "ok":
                return {
                    "status": "failed",
                    "reason": "source_database_malformed",
                    "integrity_check": integridad,
                    "source": str(self.db_path),
                    "detail": (
                        "no se archiva una copia de una base dañada: taparía a "
                        "las copias buenas que aún existen"
                    ),
                }
            snapshot_bytes = snapshot.read_bytes()
            plaintext = gzip.compress(snapshot_bytes)
        encrypted = self._fernet().encrypt(plaintext)
        digest = hashlib.sha256(encrypted).hexdigest()
        output = (
            self.backup_dir / f"triade-{int(time.time())}-{digest[:12]}.db.gz.fernet"
        )
        output.write_bytes(encrypted)
        output.chmod(0o600)
        manifest = {
            "file": output.name,
            "sha256": digest,
            "source": str(self.db_path),
            "encrypted": True,
            "created_at": time.time(),
            "source_db_sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
            "source_size_bytes": len(snapshot_bytes),
            # Sin esto, los backups del 2026-07-30 quedaron sin poder emparejarse
            # con ninguna clave: el manifiesto no decía cuál los había cifrado.
            "key_fingerprint": self.key_fingerprint(),
            # Qué dijo `integrity_check` sobre el origen en el momento de copiar.
            # Queda escrito para que saberlo no cueste descifrar 60 MB: el
            # detector de deuda lo lee del manifiesto.
            "source_integrity": integridad,
        }
        manifest_path = output.with_suffix(output.suffix + ".json")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        manifest_path.chmod(0o600)
        return {"status": "completed", **manifest}

    def verify(self, backup: str | Path) -> dict[str, Any]:
        backup_path = Path(backup)
        encrypted = backup_path.read_bytes()
        manifest_path = backup_path.with_suffix(backup_path.suffix + ".json")
        if not manifest_path.is_file():
            raise ValueError("backup_manifest_missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        encrypted_hash = hashlib.sha256(encrypted).hexdigest()
        if encrypted_hash != manifest.get("sha256"):
            raise ValueError("encrypted_backup_hash_mismatch")
        raw = gzip.decompress(self._fernet().decrypt(encrypted))
        if hashlib.sha256(raw).hexdigest() != manifest.get("source_db_sha256"):
            raise ValueError("restored_database_hash_mismatch")
        with tempfile.TemporaryDirectory(prefix="triade-restore-test-") as directory:
            test_db = Path(directory) / "restore.db"
            test_db.write_bytes(raw)
            semantic = self._semantic_verification(test_db)
            if (
                self.require_identity_manifest
                and not semantic["identity_manifest_hash"]
            ):
                raise ValueError("identity_manifest_missing")
        return {
            "status": "ok" if semantic["integrity_check"] == "ok" else "error",
            "sha256": encrypted_hash,
            **semantic,
        }

    @staticmethod
    def _semantic_verification(db_path: Path) -> dict[str, Any]:
        with sqlite3.connect(db_path) as conn:
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            # El simulacro de restauración verificaba el saber semántico
            # contando `semantic_memory`, que tiene cero filas y ningún `INSERT`
            # en todo el repositorio. O sea: la comprobación que debía detectar
            # una restauración que perdiera la memoria semántica **daba 0 tanto
            # si se perdía como si no**. Con 379 documentos vivos en
            # `semantic_documents` (2026-08-11), el simulacro no podía fallar
            # por esa vía ni cuando debía.
            #
            # Se cuenta la tabla que sostiene el saber, y se deja la vieja como
            # respaldo por si una base antigua sólo tiene aquélla.
            if "semantic_documents" in tables:
                memory_count = conn.execute(
                    "SELECT COUNT(*) FROM semantic_documents"
                ).fetchone()[0]
            elif "semantic_memory" in tables:
                memory_count = conn.execute(
                    "SELECT COUNT(*) FROM semantic_memory"
                ).fetchone()[0]
            else:
                memory_count = 0
            task_states = (
                dict(
                    conn.execute(
                        "SELECT status,COUNT(*) FROM autonomous_tasks GROUP BY status"
                    )
                )
                if "autonomous_tasks" in tables
                else {}
            )
            identity_anchor = (
                conn.execute(
                    "SELECT manifest_hash FROM identity_manifest_anchor WHERE singleton=1"
                ).fetchone()
                if "identity_manifest_anchor" in tables
                else None
            )
            artifacts_checked = 0
            artifact_failures: list[str] = []
            if "autonomous_tasks" in tables:
                for (result_ref,) in conn.execute(
                    "SELECT result_ref FROM autonomous_tasks WHERE result_ref IS NOT NULL"
                ):
                    path = Path(str(result_ref))
                    if path.is_file():
                        artifacts_checked += 1
                    else:
                        artifact_failures.append(str(path))
        return {
            "integrity_check": integrity,
            "identity_manifest_hash": identity_anchor[0] if identity_anchor else None,
            "semantic_memory_count": memory_count,
            "task_states": task_states,
            "artifact_refs_checked": artifacts_checked,
            "artifact_ref_failures": artifact_failures,
        }

    def enforce_retention(
        self, *, keep_daily: int = 7, keep_weekly: int = 4
    ) -> dict[str, Any]:
        """Conserva los N diarios recientes y una muestra semanal; nunca borra el último."""
        files = sorted(
            self.backup_dir.glob("triade-*.db.gz.fernet"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        keep: set[Path] = set(files[: max(1, keep_daily)])
        weeks: set[str] = set()
        for path in files[max(1, keep_daily) :]:
            week = time.strftime("%Y-%W", time.gmtime(path.stat().st_mtime))
            if len(weeks) < max(0, keep_weekly) and week not in weeks:
                weeks.add(week)
                keep.add(path)
        removed = []
        for path in files:
            if path in keep:
                continue
            manifest = path.with_suffix(path.suffix + ".json")
            quarantine = self.backup_dir / "quarantine"
            quarantine.mkdir(parents=True, exist_ok=True)
            shutil.move(str(path), quarantine / path.name)
            if manifest.exists():
                shutil.move(str(manifest), quarantine / manifest.name)
            removed.append(path.name)
        return {
            "status": "completed",
            "kept": len(keep),
            "removed": removed,
            "policy": {"daily": keep_daily, "weekly": keep_weekly},
            "quarantine_dir": str(self.backup_dir / "quarantine"),
            "bytes_kept": sum(path.stat().st_size for path in keep if path.exists()),
        }

    def restore_to_sandbox(
        self, backup: str | Path, destination: str | Path
    ) -> dict[str, Any]:
        verification = self.verify(backup)
        encrypted = Path(backup).read_bytes()
        raw = gzip.decompress(self._fernet().decrypt(encrypted))
        target = Path(destination)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="triade-sandbox-restore-") as directory:
            source_path = Path(directory) / "source.db"
            source_path.write_bytes(raw)
            with (
                sqlite3.connect(source_path) as source,
                sqlite3.connect(target) as output,
            ):
                source.backup(output)
        restored = self._semantic_verification(target)
        return {
            "status": "restored_sandbox"
            if restored["integrity_check"] == "ok"
            else "error",
            "destination": str(target),
            "production_overwritten": target.resolve() == self.db_path.resolve(),
            "verification": verification,
            "restored": restored,
        }

    def restore(self, backup: str | Path, *, human_approved: bool) -> dict[str, Any]:
        if not human_approved:
            return {"status": "blocked", "reason": "human_approval_required"}
        verification = self.verify(backup)
        if verification["status"] != "ok":
            return verification
        pre_restore = self.create(force=True)
        raw = gzip.decompress(self._fernet().decrypt(Path(backup).read_bytes()))
        with tempfile.TemporaryDirectory(
            prefix="triade-production-restore-"
        ) as directory:
            source_path = Path(directory) / "source.db"
            source_path.write_bytes(raw)
            with (
                sqlite3.connect(source_path) as source,
                sqlite3.connect(self.db_path) as target,
            ):
                source.backup(target)
        return {
            "status": "restored",
            "verification": verification,
            "pre_restore_backup": pre_restore,
        }

    def storage_metrics(
        self, *, artifacts_root: str | Path | None = None
    ) -> dict[str, int]:
        root = Path(artifacts_root) if artifacts_root else self.backup_dir.parent

        def bytes_under(path: Path) -> int:
            if not path.exists():
                return 0
            return sum(
                item.stat().st_size for item in path.rglob("*") if item.is_file()
            )

        return {
            "backup_bytes": bytes_under(self.backup_dir),
            "snapshot_bytes": bytes_under(root / "recovery"),
            "artifact_bytes": bytes_under(root),
        }

    def run_restore_drill(
        self,
        backup: str | Path | None = None,
        *,
        sandbox_dir: str | Path = "artifacts/restore-drills",
        artifacts_root: str | Path | None = None,
        minimum_interval_seconds: int = 604800,
        force: bool = False,
    ) -> dict[str, Any]:
        now = datetime.now(UTC)
        with sqlite3.connect(self.db_path) as conn:
            previous = conn.execute(
                "SELECT created_at,backup_bytes,snapshot_bytes,artifact_bytes "
                "FROM backup_restore_drills ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        if previous and not force:
            elapsed = (now - datetime.fromisoformat(str(previous[0]))).total_seconds()
            if elapsed < max(0, minimum_interval_seconds):
                return {
                    "status": "blocked",
                    "reason": "restore_drill_cooldown_active",
                    "seconds_until_next": round(minimum_interval_seconds - elapsed, 3),
                }
        backup_path = Path(backup) if backup else self._latest_backup()
        drill_id = f"restore-drill-{uuid.uuid4().hex[:16]}"
        sandbox = Path(sandbox_dir) / f"{drill_id}.db"
        restored = self.restore_to_sandbox(backup_path, sandbox)
        semantic = restored["restored"]
        storage = self.storage_metrics(artifacts_root=artifacts_root)
        previous_artifact_bytes = int(previous[3]) if previous else None
        growth = (
            storage["artifact_bytes"] - previous_artifact_bytes
            if previous_artifact_bytes is not None
            else None
        )
        status = (
            "completed"
            if restored["status"] == "restored_sandbox"
            and semantic["integrity_check"] == "ok"
            and not restored["production_overwritten"]
            else "failed"
        )
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO backup_restore_drills VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    drill_id,
                    str(backup_path),
                    status,
                    str(sandbox),
                    semantic["integrity_check"],
                    semantic["identity_manifest_hash"],
                    int(semantic["semantic_memory_count"]),
                    json.dumps(semantic["task_states"], sort_keys=True),
                    storage["backup_bytes"],
                    storage["snapshot_bytes"],
                    storage["artifact_bytes"],
                    growth,
                    now.isoformat(),
                ),
            )
        return {
            "drill_id": drill_id,
            "status": status,
            "backup_ref": str(backup_path),
            "sandbox_ref": str(sandbox),
            "production_overwritten": restored["production_overwritten"],
            "semantic_verification": semantic,
            "storage": storage,
            "growth_bytes": growth,
            "created_at": now.isoformat(),
        }

    def _latest_backup(self) -> Path:
        backups = sorted(
            self.backup_dir.glob("triade-*.db.gz.fernet"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if not backups:
            raise FileNotFoundError("encrypted_backup_not_found")
        return backups[0]
