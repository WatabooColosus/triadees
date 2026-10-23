"""Create the first verified owner locally; no public admin-registration API.

Usage (trusted Colab terminal/cell):
  python tools/bootstrap_owner_account.py --db triade/memory/triade.db --email you@example.com
The password is entered with getpass and is never passed on the command line.
Existing installations with any users refuse bootstrap to prevent privilege
escalation by an operator with console access to a running database.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from triade.security.public_auth import PublicAuthStore


def bootstrap(db_path: Path, email: str, password: str) -> dict[str, str]:
    """Atomic creation of one owner account, verified via trusted local console."""
    if not db_path.is_file():
        raise FileNotFoundError("La base de Tríade no existe; inicia el servidor primero")
    normalized = PublicAuthStore.normalize_email(email)
    if not 12 <= len(password) <= 1024 or not password.strip():
        raise ValueError("strong_password_required")
    store = PublicAuthStore(db_path)
    now = datetime.now(UTC).isoformat()
    user_id = f"usr-{uuid.uuid4().hex}"
    with sqlite3.connect(db_path, timeout=30) as conn:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT COUNT(*) FROM auth_users").fetchone()[0] != 0:
            raise PermissionError("bootstrap_refused_existing_accounts")
        conn.execute(
            "INSERT INTO auth_users VALUES (?, ?, ?, 'admin', 'local', 0, 0, NULL, ?)",
            (user_id, normalized, store.hasher.hash(password), now),
        )
        conn.execute(
            "INSERT INTO auth_email_identities VALUES (?, ?, ?, NULL, NULL, ?)",
            (user_id, normalized, now, now),
        )
    return {"status": "created", "role": "admin", "verification": "local_trusted_bootstrap"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--email", required=True)
    args = parser.parse_args()
    if os.getenv("TRIADE_LOCAL_NO_AUTH", "0").strip() == "1":
        parser.error("Desactiva TRIADE_LOCAL_NO_AUTH antes de crear el propietario")
    first = getpass.getpass("Contraseña del propietario (mínimo 12 caracteres): ")
    second = getpass.getpass("Repite la contraseña: ")
    if first != second:
        parser.error("Las contraseñas no coinciden")
    result = bootstrap(args.db, args.email, first)
    print(
        "Propietario inicial creado con correo verificado localmente. "
        "Inicia sesión en el panel. No compartas tu contraseña."
    )
    return 0 if result["status"] == "created" else 1


if __name__ == "__main__":
    raise SystemExit(main())
