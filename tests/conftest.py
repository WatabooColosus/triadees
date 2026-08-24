import os
import tempfile
from pathlib import Path

import pytest

_ORIGINAL_CWD: str | None = None


@pytest.fixture(autouse=True)
def isolate_contract_tests_from_host_load(request, monkeypatch):
    """Evita que el orden de la suite convierta carga del host en resultados.

    La política del Resource Governor conserva su probe real en su propia
    suite. El resto de pruebas usa RAM/disco/modelos reales, pero no hereda el
    load average producido por los constructores de grafos ejecutados antes.
    """
    if request.node.path.name == "test_resource_governor.py":
        yield
        return
    from triade.core import resource_probe

    original = resource_probe.build_resource_probe

    def stable_load():
        probe = original()
        probe["cpu"]["load_1min"] = 0.0
        return probe

    monkeypatch.setattr(resource_probe, "build_resource_probe", stable_load)
    yield


def pytest_configure(config):
    global _ORIGINAL_CWD
    os.environ["TRIADE_RUNTIME_SCOPE"] = "test"
    _ORIGINAL_CWD = os.getcwd()
    root = Path(tempfile.mkdtemp(prefix="triade-pytest-session-"))
    source_root = Path(_ORIGINAL_CWD)
    memory = root / "triade" / "memory"
    memory.mkdir(parents=True)
    (root / "runs").mkdir()
    (root / "artifacts").mkdir()
    (memory / "schemas.sql").symlink_to(
        source_root / "triade" / "memory" / "schemas.sql"
    )
    (memory / "migrations").symlink_to(
        source_root / "triade" / "memory" / "migrations", target_is_directory=True
    )
    (root / "scripts").symlink_to(source_root / "scripts", target_is_directory=True)
    (root / "docs").symlink_to(source_root / "docs", target_is_directory=True)
    for name in (
        "triade.yml",
        "triade_digimon.py",
        "pyproject.toml",
        "requirements.txt",
        ".env.example",
    ):
        source = source_root / name
        if source.exists():
            (root / name).symlink_to(source)
    os.environ["TRIADE_TEST_ROOT"] = str(root)
    os.environ["TRIADE_DISABLE_BACKGROUND"] = "1"
    os.chdir(root)


def pytest_unconfigure(config):
    if _ORIGINAL_CWD:
        os.chdir(_ORIGINAL_CWD)
    os.environ.pop("TRIADE_RUNTIME_SCOPE", None)
    os.environ.pop("TRIADE_DISABLE_BACKGROUND", None)
