from pathlib import Path

import pytest

from triade.evolution.engineering_worker import (
    EngineeringEvolutionWorker,
    EvolutionBudget,
)


def test_protected_paths_and_file_budget():
    with pytest.raises(ValueError, match="protected_path"):
        EngineeringEvolutionWorker._validate_files(
            ["triade/memory/schemas.sql"], EvolutionBudget()
        )
    with pytest.raises(ValueError, match="protected_path"):
        EngineeringEvolutionWorker._validate_files(
            ["tests/test_gate.py"], EvolutionBudget()
        )
    with pytest.raises(ValueError, match="file_budget"):
        EngineeringEvolutionWorker._validate_files(
            [f"triade/x{i}.py" for i in range(13)], EvolutionBudget()
        )


def test_independent_review_never_accepts_failed_candidate():
    review = EngineeringEvolutionWorker._review(
        {"passed": True}, {"passed": False}, ["triade/x.py"]
    )
    assert review["decision"] == "reject_candidate"
    assert review["independent_tests"] is True


def test_commit_requires_named_approval(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    worker = EngineeringEvolutionWorker(repo, tmp_path / "db.sqlite")
    assert worker.approve_and_commit("missing", approved_by="")["status"] == "blocked"


def test_el_vocabulario_declarado_cubre_todo_lo_que_se_escribe():
    """La fuente canónica no puede quedarse corta, o vuelve el estado fantasma.

    `evaluating` existió sólo en un `WHERE status IN ('preparing','evaluating')`:
    ningún camino del worker lo escribía, así que la mitad de esa condición no
    podía casar nunca. Salió al centralizar el vocabulario en `EVOLUTION_STATES`.

    Aquí se recogen los estados que el módulo escribe de verdad —el `INSERT`, los
    `UPDATE ... SET status='...'`, lo que se asigna a `status` (incluidas las dos
    ramas de un ternario) y lo que se pasa a `self._status(...)`— y se exige que
    coincidan **exactamente** con lo declarado. Si alguien añade un estado sin
    declararlo, o declara uno que ningún camino escribe, se entera aquí.
    """
    import ast
    import re
    from pathlib import Path

    from triade.evolution.engineering_worker import (
        EVOLUTION_IN_FLIGHT,
        EVOLUTION_STATES,
    )
    from triade.observability.alias_debt import _insert_values

    ruta = (
        Path(__file__).resolve().parents[1] / "triade/evolution/engineering_worker.py"
    )
    fuente = ruta.read_text(encoding="utf-8")
    arbol = ast.parse(fuente)

    escritos: set[str] = set()
    # SQL literal: `SET status='x'`, y el `INSERT` con el mismo emparejamiento
    # por posición que usa el detector de deuda — así las dos lecturas del
    # esquema no pueden divergir.
    escritos |= set(re.findall(r"SET status='([a-z_]+)'", fuente))
    escritos |= _insert_values(fuente)

    def _literales(nodo: ast.AST) -> set[str]:
        return {
            hijo.value
            for hijo in ast.walk(nodo)
            if isinstance(hijo, ast.Constant) and isinstance(hijo.value, str)
        }

    for nodo in ast.walk(arbol):
        # `status = "a" if cond else "b"` — escriben las dos ramas, no la
        # condición: mirar el nodo entero recogía `accept_candidate`, que es un
        # veredicto de revisión y no un estado de la ejecución.
        if isinstance(nodo, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "status" for t in nodo.targets
        ):
            valor = nodo.value
            ramas = (
                [valor.body, valor.orelse] if isinstance(valor, ast.IfExp) else [valor]
            )
            for rama in ramas:
                escritos |= _literales(rama)
        # `self._status(eid, "failed")` — el helper hace el UPDATE.
        if (
            isinstance(nodo, ast.Call)
            and isinstance(nodo.func, ast.Attribute)
            and nodo.func.attr == "_status"
            and len(nodo.args) == 2
        ):
            escritos |= _literales(nodo.args[1])

    assert escritos, "la prueba no encontró ninguna escritura: revisa los patrones"
    assert escritos == set(EVOLUTION_STATES), (
        f"escritos y no declarados: {sorted(escritos - EVOLUTION_STATES)}; "
        f"declarados y no escritos: {sorted(EVOLUTION_STATES - escritos)}"
    )
    assert EVOLUTION_IN_FLIGHT <= EVOLUTION_STATES
