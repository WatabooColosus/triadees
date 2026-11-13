"""El documento que declara las herramientas manuales no puede ser ficción.

`code_graph.build_entrypoint_graph` marca `legacy` —y por tanto fuera del
recuento de deuda— a todo entrypoint citado en la documentación, con este
razonamiento, que es del repositorio y no de esta prueba:

    Una herramienta que la documentación explica cómo ejecutar no es código
    muerto: es manual.

Eso convierte a la documentación en parte del detector, y abre una trampa
evidente: citar un fichero cualquiera baja el contador. Estas pruebas cierran la
trampa por el único lado que importa: lo citado tiene que existir y tiene que
ser realmente un entrypoint.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs/scripts/MANUAL_TOOLS.md"


def _scripts_citados() -> set[str]:
    texto = DOC.read_text(encoding="utf-8")
    return set(re.findall(r"scripts/[\w./-]+\.py", texto))


def test_el_documento_existe_y_cita_scripts() -> None:
    assert DOC.exists(), "sin el documento, 17 herramientas vuelven a ser deuda"
    assert _scripts_citados(), "un documento que no cita nada no declara nada"


def test_todo_lo_citado_existe() -> None:
    """Citar un fichero inexistente bajaría el contador sin declarar nada."""
    ausentes = sorted(s for s in _scripts_citados() if not (REPO_ROOT / s).is_file())

    assert not ausentes, f"el documento cita scripts que no existen: {ausentes}"


def test_todo_lo_citado_es_un_entrypoint_real() -> None:
    """Sin guard `__main__` no es una herramienta ejecutable, es otra cosa."""
    sin_guard: list[str] = []
    for relativo in sorted(_scripts_citados()):
        arbol = ast.parse((REPO_ROOT / relativo).read_text(encoding="utf-8"))
        tiene = any(
            isinstance(nodo, ast.If)
            and isinstance(nodo.test, ast.Compare)
            and isinstance(nodo.test.left, ast.Name)
            and nodo.test.left.id == "__name__"
            for nodo in ast.walk(arbol)
        )
        if not tiene:
            sin_guard.append(relativo)

    assert not sin_guard, f"citados como ejecutables sin `__main__`: {sin_guard}"
