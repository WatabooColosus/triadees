#!/usr/bin/env python3
"""Busca actualizaciones de Tríade comparando el historial Git, no texto de commits."""
from __future__ import annotations

import argparse
import json
import subprocess
import urllib.request
from pathlib import Path

URL = "https://raw.githubusercontent.com/WatabooColosus/triadees/codex/triade-5.8.0-runtime-recovery/releases/manifest.json"

def git(root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(["git", "-C", str(root), *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return None

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    args = ap.parse_args()
    root = Path(args.root)
    with urllib.request.urlopen(URL, timeout=15) as response:
        remote = json.load(response)
    head = git(root, "rev-parse", "HEAD")
    remote_commit = str(remote.get("commit") or "")
    relation = "unknown"
    update_available = False
    if head and remote_commit:
        if head == remote_commit:
            relation = "same"
        elif git(root, "merge-base", "--is-ancestor", remote_commit, head) is not None:
            # Remote release is already included in the local branch.
            relation = "local_ahead_or_equal"
        else:
            relation = "remote_not_ancestor"
            update_available = True
    result = {
        "status": "ok",
        "remote": remote,
        "local_commit": head,
        "relation": relation,
        "update_available": update_available,
        "source": URL,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
