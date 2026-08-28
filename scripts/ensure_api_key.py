#!/usr/bin/env python3
"""Configura una API key local fuerte sin imprimirla en stdout ni logs."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import tempfile
from pathlib import Path

TRIADE_ENTRYPOINT_KIND = "administrative_on_demand"


def _write_key(
    env_path: Path, value: str, *, replace_existing: bool
) -> dict[str, object]:
    if not value or "\n" in value or "\r" in value:
        raise ValueError("api_key_must_be_one_non_empty_line")
    original = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = original.splitlines()
    found = False
    configured = False
    updated: list[str] = []
    for line in lines:
        if line.startswith("TRIADE_API_KEY="):
            found = True
            current = line.partition("=")[2].strip().strip("\"'")
            if current and not replace_existing:
                configured = True
                updated.append(line)
            else:
                updated.append(f"TRIADE_API_KEY={value}")
            continue
        updated.append(line)
    if not found:
        updated.append(f"TRIADE_API_KEY={value}")
    if configured:
        return {"status": "already_configured", "path": str(env_path)}

    env_path.parent.mkdir(parents=True, exist_ok=True)
    previous_mode = env_path.stat().st_mode & 0o777 if env_path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".triade-env-", dir=env_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(updated) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, previous_mode)
        os.replace(temporary, env_path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {
        "status": "configured",
        "path": str(env_path),
        "secret_printed": False,
        "length": len(value),
    }


def ensure_api_key(env_path: Path) -> dict[str, object]:
    return _write_key(env_path, secrets.token_urlsafe(48), replace_existing=False)


def rotate_api_key(env_path: Path, value: str) -> dict[str, object]:
    result = _write_key(env_path, value, replace_existing=True)
    result["status"] = "rotated"
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument(
        "--rotate-from-stdin",
        action="store_true",
        help="lee la nueva clave de una línea de stdin sin imprimirla",
    )
    args = parser.parse_args()
    result = (
        rotate_api_key(args.env_file, sys.stdin.readline().rstrip("\r\n"))
        if args.rotate_from_stdin
        else ensure_api_key(args.env_file)
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
