import os
import shutil
import tempfile
from pathlib import Path

import pytest

_ORIGINAL_CWD: str | None = None


def _link_or_copy(destination: Path, source: Path) -> None:
    try:
        destination.symlink_to(source, target_is_directory=source.is_dir())
    except OSError as exc:
        if getattr(exc, "winerror", None) != 1314:
            raise
        if source.is_dir():
            shutil.copytree(source, destination)
        else:
            shutil.copy2(source, destination)


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
    _link_or_copy(memory / "schemas.sql",
        source_root / "triade" / "memory" / "schemas.sql"
    )
    _link_or_copy(memory / "migrations",
        source_root / "triade" / "memory" / "migrations"
    )
    _link_or_copy(root / "scripts", source_root / "scripts")
    _link_or_copy(root / "docs", source_root / "docs")
    for name in (
        "triade.yml",
        "triade_digimon.py",
        "pyproject.toml",
        "requirements.txt",
        ".env.example",
    ):
        source = source_root / name
        if source.exists():
            _link_or_copy(root / name, source)
    os.environ["TRIADE_TEST_ROOT"] = str(root)
    os.environ["TRIADE_DISABLE_BACKGROUND"] = "1"
    os.chdir(root)


def pytest_unconfigure(config):
    if _ORIGINAL_CWD:
        os.chdir(_ORIGINAL_CWD)
    os.environ.pop("TRIADE_RUNTIME_SCOPE", None)
    os.environ.pop("TRIADE_DISABLE_BACKGROUND", None)
