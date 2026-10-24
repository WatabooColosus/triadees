"""Owner-operated backup-key unlock; never invoke from API, worker, or boot.

The operator must explicitly select --unlock, pass the expected auth lineage,
and enter a recovery phrase through a local TTY. No secrets appear in JSON output.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path

from triade.security.session_backup_key_vault import unlock_or_create


def unlock(
    *,
    db: Path,
    index: Path,
    drive_vault_dir: Path,
    local_private_dir: Path,
    expected_lineage: str,
    passphrase: str,
) -> dict[str, str]:
    """One-shot manual operation; no background service or key rotation."""
    if not index.is_file() or index.is_symlink():
        raise RuntimeError("No hay índice de continuidad local verificable")
    payload = json.loads(index.read_text(encoding="utf-8"))
    if payload.get("guard") != "wal_closed_and_rows_verified_v1":
        raise RuntimeError("Continuidad no protegida: no se desbloquea el vault")
    if payload.get("lineage") != expected_lineage:
        raise RuntimeError("Linaje no coincide con el autorizado")
    result = unlock_or_create(db, index, drive_vault_dir, local_private_dir, passphrase)
    if result["identity_lineage"] != expected_lineage:
        raise RuntimeError("Vault no corresponde al linaje autorizado")
    # Never print the passphrase, wrapped key, key file bytes or environment.
    return {
        "status": result["status"],
        "identity_lineage": result["identity_lineage"],
        "fingerprint": result["fingerprint"],
        "vault_encrypted": result["vault_encrypted"],
        "key_storage": "private_local_file",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--unlock", action="store_true", help="Aprobación manual explícita"
    )
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--drive-vault-dir", type=Path, required=True)
    parser.add_argument("--local-private-dir", type=Path, required=True)
    parser.add_argument("--confirm-lineage", required=True)
    args = parser.parse_args(argv)
    if not args.unlock:
        parser.error("Falta --unlock; no se generan ni recuperan claves")
    if not sys.stdin.isatty():
        parser.error(
            "Se requiere TTY privado; no se aceptan frases en CLI, log ni notebook"
        )
    phrase = getpass.getpass("Frase de recuperación (no visible): ")
    if len(phrase) < 14:
        parser.error("La frase debe tener por lo menos 14 caracteres")
    # Do not request confirmation twice on an existing encrypted vault: the
    # key should remain unchanged, and the vault layer rejects a bad phrase.
    result = unlock(
        db=args.db,
        index=args.index,
        drive_vault_dir=args.drive_vault_dir,
        local_private_dir=args.local_private_dir,
        expected_lineage=args.confirm_lineage,
        passphrase=phrase,
    )
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
