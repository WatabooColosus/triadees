"""Verifica el canal de actualizaciones de Tríade sin cambiar el runtime.

La actualización sólo debe ofrecerse después de promoción explícita de
stable-candidate a stable, con manifiesto que coincida con el HEAD remoto.
Una revisión pendiente no es una nueva versión instalable.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

URL = (
    "https://raw.githubusercontent.com/WatabooColosus/triadees/"
    "codex/triade-5.8.0-runtime-recovery/releases/manifest.json"
)
SHA = re.compile(r"^[0-9a-f]{40}$")
BRANCH = re.compile(r"^codex/[A-Za-z0-9][A-Za-z0-9._/-]*$")


def git(root: Path, *args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(root), *args],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=40,
        ).strip()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def decision(
    manifest: dict[str, Any],
    *,
    head: str | None,
    release_tree_verified: bool = False,
    remote_is_ancestor: bool | None = None,
    local_is_ancestor: bool | None = None,
) -> dict[str, Any]:
    """Política verificable y sin efectos; no infiere un release por la versión."""
    commit = str(manifest.get("commit") or "")
    branch = str(manifest.get("branch") or "")
    if (
        manifest.get("project") != "triadees"
        or not SHA.fullmatch(commit)
        or not BRANCH.fullmatch(branch)
    ):
        return {"status": "invalid_manifest", "relation": "unknown", "update_available": False}
    if manifest.get("requires_review") is not False or manifest.get("channel") != "stable":
        return {
            "status": "review_required",
            "relation": "candidate_not_released",
            "update_available": False,
        }
    if not release_tree_verified:
        return {
            "status": "manifest_mismatch",
            "relation": "release_commit_not_verified_on_branch",
            "update_available": False,
        }
    if head == commit:
        return {"status": "ok", "relation": "same", "update_available": False}
    if remote_is_ancestor is True:
        return {
            "status": "ok",
            "relation": "local_ahead_or_equal",
            "update_available": False,
        }
    if local_is_ancestor is True:
        return {"status": "ok", "relation": "fast_forward_available", "update_available": True}
    return {
        "status": "manual_review_required",
        "relation": "unknown_or_diverged",
        "update_available": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    with urllib.request.urlopen(URL, timeout=15) as response:
        remote = json.load(response)
    if not isinstance(remote, dict):
        raise ValueError("release_manifest_must_be_object")
    head = git(root, "rev-parse", "HEAD")
    branch = str(remote.get("branch") or "")
    commit = str(remote.get("commit") or "")
    release_tree_verified = False
    older: bool | None = None
    newer: bool | None = None
    # La comprobación externa sólo se necesita cuando el canal está aprobado.
    # git fetch actualiza objetos Git, jamás el working tree ni la DB de Colab.
    if (
        SHA.fullmatch(commit)
        and BRANCH.fullmatch(branch)
        and remote.get("channel") == "stable"
        and remote.get("requires_review") is False
    ):
        ls = git(root, "ls-remote", "origin", f"refs/heads/{branch}")
        tip = ls.split()[0] if ls else None
        if (
            tip
            and git(root, "fetch", "--no-tags", "origin", branch) is not None
            and git(root, "merge-base", "--is-ancestor", commit, tip) is not None
        ):
            # El manifiesto está en la MISMA rama, por eso su commit siempre
            # va después del commit de código que anuncia. Desde el release
            # únicamente se permiten cambios del propio manifiesto.
            changed = git(root, "diff", "--name-only", commit, tip)
            if changed is not None and set(changed.splitlines()) <= {"releases/manifest.json"}:
                release_tree_verified = True
                older = git(root, "merge-base", "--is-ancestor", commit, head) is not None
                newer = git(root, "merge-base", "--is-ancestor", head, commit) is not None
    result = {
        **decision(
            remote,
            head=head,
            release_tree_verified=release_tree_verified,
            remote_is_ancestor=older,
            local_is_ancestor=newer,
        ),
        "remote": remote,
        "local_commit": head,
        "source": URL,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
