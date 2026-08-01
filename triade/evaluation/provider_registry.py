"""Registro cerrado de `evaluation_provider`.

Un `EvaluationProvider` decide **con qué vara se mide** una candidata. Aceptar un
nombre arbitrario desde el payload de una tarea permitiría que una propuesta
eligiera su propio examinador, que es exactamente la forma más limpia de que un
sistema se declare mejorado sin haberlo sido.

Por eso el registro es cerrado: un nombre que no esté aquí no se resuelve, y la
tarea falla en vez de improvisar.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from triade.evaluation.vitality_provider import VitalityEvaluationProvider

#: Nombre autorizado → constructor. Añadir una entrada es una decisión de
#: gobierno, no de conveniencia.
EVALUATION_PROVIDERS: dict[str, Callable[[Path], Any]] = {
    "triade_vitality": lambda db_path: VitalityEvaluationProvider(db_path),
}

DEFAULT_EVALUATION_PROVIDER = "triade_vitality"


def build_evaluation_provider(name: str, db_path: str | Path) -> Any:
    """Construye el provider autorizado, o falla con los nombres válidos."""
    key = (name or DEFAULT_EVALUATION_PROVIDER).strip()
    factory = EVALUATION_PROVIDERS.get(key)
    if factory is None:
        allowed = ", ".join(sorted(EVALUATION_PROVIDERS))
        raise ValueError(
            f"evaluation_provider no autorizado: {key!r}; permitidos: {allowed}"
        )
    return factory(Path(db_path))
