"""Tríade Ω: per-auth-lineage backup key vault.

Vault contains only a password-wrapped Fernet key. Plaintext key exists in
private Colab runtime memory/file; never commit/export/print it. Lost old keys
cannot be recovered and existing backups must remain untouched.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

VERSION = 1


def _lineage(db_path: Path) -> str:
    if not db_path.is_file():
        raise RuntimeError("No hay Bodega; no se crea ninguna clave")
    with sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True) as db:
        if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite no supera la prueba de integridad")
        owners = [str(row[0]) for row in db.execute("SELECT user_id FROM auth_users")]
    if len(owners) != 1:
        raise RuntimeError("Se necesita una sola cuenta propietaria; identidades múltiples bloqueadas")
    return hashlib.sha256("\n".join(sorted(owners)).encode()).hexdigest()[:16]


def _wrap_key(passphrase: str, salt: bytes) -> bytes:
    if not passphrase or len(passphrase) < 14:
        raise ValueError("La frase de recuperación debe tener al menos 14 caracteres")
    key = Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode("utf-8"))
    return base64.urlsafe_b64encode(key)


def _fingerprint(key: bytes) -> str:
    return hashlib.sha256(b"triade-omega-backup-v1:" + key).hexdigest()[:20]


def _private_local_file(path: Path, secret: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    if path.is_symlink():
        raise RuntimeError("No se admite enlace simbólico para la clave")
    if path.exists():
        if not hmac.compare_digest(path.read_bytes(), secret):
            raise RuntimeError("Existe otra clave local para esta identidad; no se reemplaza")
        path.chmod(0o600)
        return
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(secret)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    path.chmod(0o600)


def unlock_or_create(
    db_path: Path,
    continuity_index: Path,
    drive_vault_dir: Path,
    local_private_dir: Path,
    passphrase: str,
) -> dict[str, Any]:
    """Create once per verified auth lineage, or unlock the existing key.

    O_EXCL + fail closed prevents overwriting old identity keys. JSON in Drive
    holds only password-encrypted key; never returns the key in results.
    """
    db_path = Path(db_path)
    continuity_index = Path(continuity_index)
    if not continuity_index.is_file():
        raise RuntimeError("Falta active.json de continuidad; sin selección segura de identidad")
    active = json.loads(continuity_index.read_text(encoding="utf-8"))
    lineage = _lineage(db_path)
    if lineage != active.get("lineage"):
        raise RuntimeError("La identidad de la SQLite no coincide con la sesión única del Drive")
    vault_dir = Path(drive_vault_dir)
    if not vault_dir.parent.is_dir():
        raise RuntimeError("No se encuentra la continuidad montada en Drive")
    vault_dir.mkdir(parents=True, exist_ok=True)
    vault_path = vault_dir / f"backup-v1-{lineage}.json"
    if vault_path.is_symlink():
        raise RuntimeError("Vault enlazado: acceso denegado")
    new_vault = not vault_path.exists()
    if new_vault:
        secret = Fernet.generate_key()
        salt = os.urandom(16)
        wrapped = Fernet(_wrap_key(passphrase, salt)).encrypt(secret)
        document = {
            "version": VERSION,
            "kind": "triade-owner-lineage-encrypted-backup-key",
            "lineage": lineage,
            "kdf": "scrypt-n32768-r8-p1",
            "salt": base64.b64encode(salt).decode("ascii"),
            "wrapped_key": wrapped.decode("ascii"),
            "key_fingerprint": _fingerprint(secret),
            "old_key_recoverable": False,
        }
        fd = os.open(str(vault_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(document, file, sort_keys=True, indent=2)
                file.flush()
                os.fsync(file.fileno())
        except BaseException:
            vault_path.unlink(missing_ok=True)
            raise
    else:
        document = json.loads(vault_path.read_text(encoding="utf-8"))
        if document.get("lineage") != lineage or document.get("version") != VERSION:
            raise RuntimeError("Identidad o versión del vault no coincide; no se rota ni modifica")
        if document.get("kdf") != "scrypt-n32768-r8-p1":
            raise RuntimeError("KDF de vault inesperado: revisión manual requerida")
        salt = base64.b64decode(document["salt"], validate=True)
        if len(salt) != 16:
            raise RuntimeError("Salt del vault inválido")
        try:
            secret = Fernet(_wrap_key(passphrase, salt)).decrypt(
                document["wrapped_key"].encode("ascii")
            )
        except InvalidToken as exc:
            raise RuntimeError("Contraseña de recuperación incorrecta o vault alterado") from exc
        if not hmac.compare_digest(_fingerprint(secret), document["key_fingerprint"]):
            raise RuntimeError("Huella de clave distinta; vault no confiable")
    # Fernet constructor requires valid base64 32-byte secret.
    cipher = Fernet(secret)
    probe = cipher.encrypt(b"triade-vault-selftest")
    if cipher.decrypt(probe) != b"triade-vault-selftest":
        raise RuntimeError("La clave nueva no superó la verificación criptográfica")
    local = Path(local_private_dir) / f"backup-{lineage}.key"
    _private_local_file(local, secret)
    os.environ["TRIADE_BACKUP_KEY_FILE"] = str(local)
    os.environ.pop("TRIADE_BACKUP_KEY", None)
    os.environ["TRIADE_REQUIRE_ENCRYPTED_BACKUP"] = "1"
    return {
        "status": "created" if new_vault else "unlocked",
        "identity_lineage": lineage,
        "fingerprint": document["key_fingerprint"],
        "key_local_file": str(local),
        "vault_file": str(vault_path),
        "vault_encrypted": True,
        "old_encrypted_backup_support": "old-key-required",
    }