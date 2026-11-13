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
    runtime_scope()
    marker = os.getenv("PYTEST_CURRENT_TEST", f"pid-{os.getpid()}")
    digest = hashlib.sha256(marker.encode()).hexdigest()[:12]
    root = (
        Path(os.getenv("TRIADE_TEST_ROOT", tempfile.gettempdir()))
        / "triade-tests"
        / digest
    )
    root.mkdir(parents=True, exist_ok=True)
    return root / "triade.db", root / "runs"


#: Prefijos de `source` que no son conversación real y no deben alimentar la
#: memoria: bancos de pruebas, verificaciones y trabajo interno del propio
#: sistema. El vocabulario vivía duplicado —`runner_preflight.prepare_input` y
#: las consultas de `mission_planner` tenían cada una su lista— y las copias ya
#: habían empezado a divergir, que es como este repositorio pierde contratos.
#:
#: Motivo concreto (2026-08-08): las certificaciones `phase1-real-e2e` y
#: `full-runtime-verification` encolaban aprendizaje. 43 candidatos extraían
#: `TRIADA_VIVA` —la frase de prueba— como dato distintivo. Medir si Tríade
#: recuerda su propia frase de test no es aprender: es memorizar el andamiaje.
SOURCE_PREFIXES_SIN_APRENDIZAJE: tuple[str, ...] = (
    "system_",
    "worker",
    "background",
    "test",
    "pytest",
    "phase1-",
    "full-runtime-",
    "stability-",
    "determinism-",
    "api-test",
    "neuron_activity",
)


def source_alimenta_aprendizaje(source: str | None) -> bool:
    """¿Una conversación de esta fuente debe producir aprendizaje?"""
    limpio = str(source or "").strip().lower()
    if not limpio:
        return False
    return not limpio.startswith(SOURCE_PREFIXES_SIN_APRENDIZAJE)
