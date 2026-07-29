"""Aislamiento de producción, pruebas, canary y benchmarks."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def runtime_scope() -> str:
    if os.getenv("PYTEST_CURRENT_TEST") or os.getenv("TRIADE_RUNTIME_SCOPE") == "test":
        return "test"
    return os.getenv("TRIADE_RUNTIME_SCOPE", "production").strip() or "production"


def is_test_runtime() -> bool:
    return runtime_scope() == "test"


def isolated_runtime_paths() -> tuple[Path, Path]:
    scope = runtime_scope()
    marker = os.getenv("PYTEST_CURRENT_TEST", f"pid-{os.getpid()}")
    digest = hashlib.sha256(marker.encode()).hexdigest()[:12]
    root = Path(os.getenv("TRIADE_TEST_ROOT", tempfile.gettempdir())) / "triade-tests" / digest
    root.mkdir(parents=True, exist_ok=True)
    return root / "triade.db", root / "runs"
