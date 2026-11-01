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


def test_passing_a_and_b_is_not_proof_of_a_repair():
    """CI verde en ambas versiones no demuestra mejora funcional."""
    review = EngineeringEvolutionWorker._review(
        {"passed": True}, {"passed": True}, ["triade/worker_policy.py"]
    )
    assert review["decision"] == "reject_candidate"
    assert review["measured_functional_repair"] is False


def test_repair_gate_rejects_missing_independent_oracle_or_rollback():
    proof = {
        "baseline_regression_failed": True,
        "candidate_regression_passed": True,
        "oracle_unchanged": True,
        "rollback_verified": False,
    }
    blocked = EngineeringEvolutionWorker._review(
        {"passed": True},
        {"passed": True},
        ["triade/worker_policy.py"],
        repair_evidence=proof,
    )
    assert blocked["decision"] == "reject_candidate"
    proof["rollback_verified"] = True
    approved_for_review = EngineeringEvolutionWorker._review(
        {"passed": True},
        {"passed": True},
        ["triade/worker_policy.py"],
        repair_evidence=proof,
    )
    assert approved_for_review["decision"] == "accept_candidate"
    assert approved_for_review["rollback_verified"] is True


def test_functional_certification_with_real_isolated_git_worktrees(tmp_path):
    """Una prueba existente falla en A, pasa en B y el parche revierte exactamente."""
    import subprocess
    import time

    repo = tmp_path / "repo"
    (repo / "triade").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "triade" / "__init__.py").write_text("", encoding="utf-8")
    old = (
        "def report_failed(reason: str) -> bool:\n"
        "    return True\n"
    )
    new = (
        "def report_failed(reason: str) -> bool:\n"
        '    return reason != "cancellation_requested"\n'
    )
    (repo / "triade" / "worker_policy.py").write_text(old, encoding="utf-8")
    (repo / "tests" / "test_worker_policy.py").write_text(
        "from triade.worker_policy import report_failed\n"
        "\n"
        "def test_requested_cancel_is_not_failure():\n"
        '    assert report_failed("cancellation_requested") is False\n'
        "\n"
        "def test_unexpected_failure_stays_failure():\n"
        '    assert report_failed("runtime_exception") is True\n',
        encoding="utf-8",
    )
    for command in (
        ["git", "init"],
        ["git", "config", "user.name", "Tríade test"],
        ["git", "config", "user.email", "test@example.invalid"],
        ["git", "add", "."],
        ["git", "commit", "-m", "trusted-oracle-baseline"],
    ):
        subprocess.run(command, cwd=repo, check=True, capture_output=True)
    worker = EngineeringEvolutionWorker(repo, tmp_path / "trial.sqlite")
    baseline_commit = worker._git(["rev-parse", "HEAD"], repo).strip()
    worktree = worker.root / "treatment-test"
    worker._run(
        ["git", "worktree", "add", "--detach", str(worktree), baseline_commit],
        repo,
        30,
    )
    try:
        import difflib

        patch = "".join(
            difflib.unified_diff(
                old.splitlines(keepends=True),
                new.splitlines(keepends=True),
                fromfile="a/triade/worker_policy.py",
                tofile="b/triade/worker_policy.py",
            )
        )
        (worktree / "triade" / "worker_policy.py").write_text(
            new, encoding="utf-8"
        )
        evidence = worker._certify_repair_in_worktrees(
            baseline_commit,
            worktree,
            "tests/test_worker_policy.py",
            patch,
            EvolutionBudget(max_minutes=2),
            time.monotonic(),
            "isolated-trial",
        )
        assert evidence["baseline_regression_failed"] is True
        assert evidence["candidate_regression_passed"] is True
        assert evidence["oracle_unchanged"] is True
        assert evidence["rollback_verified"] is True
        assert evidence["production_causality_proven"] is False
        review = worker._review(
            {"passed": True},
            {"passed": True},
            ["triade/worker_policy.py"],
            repair_evidence=evidence,
        )
        assert review["decision"] == "accept_candidate"
        # La prueba del rollback NO deshace el candidato en evaluación.
        assert (worktree / "triade" / "worker_policy.py").read_text() == new
    finally:
        worker._cleanup(worktree)


def test_functional_certification_rejects_modified_independent_oracle(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    path = repo / "tests" / "test_worker_behavior.py"
    path.write_text("def test_safety(): assert True\n", encoding="utf-8")
    worker = EngineeringEvolutionWorker(repo, tmp_path / "audit.sqlite")
    import subprocess

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    worker._require_trusted_regression_test("tests/test_worker_behavior.py")
    with pytest.raises(ValueError, match="trusted_regression_test_required"):
        worker._require_trusted_regression_test("../tests/test_worker_behavior.py")
    (repo / "tests" / "test_untracked.py").write_text(
        "def test_untracked(): assert True\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="tracked_regression_test_required"):
        worker._require_trusted_regression_test("tests/test_untracked.py")


def test_old_approvals_cannot_bypass_independent_functional_certificate(tmp_path):
    """No se puede firmar o desplegar aprobaciones heredadas sin evidencia."""
    import json
    import sqlite3

    repo = tmp_path / "repo"
    repo.mkdir()
    worker = EngineeringEvolutionWorker(repo, tmp_path / "runs.sqlite")
    with sqlite3.connect(worker.db_path) as conn:
        for evolution_id, status in (
            ("legacy-awaiting", "awaiting_approval"),
            ("legacy-approved", "approved_commit"),
        ):
            conn.execute(
                "INSERT INTO engineering_evolution_runs "
                "(evolution_id,objective,hypothesis,baseline_commit,"
                "worktree_path,status,budget_json,changed_files_json,review_json) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    evolution_id,
                    "fix broken worker",
                    "retry cancel handling",
                    "baseline",
                    str(repo / "missing-worktree"),
                    status,
                    json.dumps({}),
                    json.dumps(["triade/fix.py"]),
                    json.dumps(
                        {
                            "decision": "accept_candidate",
                            "independent_tests": True,
                        }
                    ),
                ),
            )
    commit = worker.approve_and_commit("legacy-awaiting", approved_by="operator")
    assert commit == {
        "status": "blocked",
        "reason": "functional_certification_required",
    }
    deployment = worker.deploy("legacy-approved", approved_by="operator")
    assert deployment == {
        "status": "blocked",
        "reason": "functional_certification_required",
    }


def test_certification_rejects_broken_test_runner_as_fake_repair(tmp_path):
    """Un error de importación no es prueba de un defecto funcional reparable."""
    test_file = tmp_path / "test_broken_oracle.py"
    test_file.write_text(
        "from nonexisting_certification_module import missing\n"
        "\n"
        "def test_regression():\n"
        "    assert missing is True\n",
        encoding="utf-8",
    )
    receipt = EngineeringEvolutionWorker._run_trusted_regression(
        tmp_path, test_file.name, 35
    )
    assert receipt["returncode"] != 0
    assert receipt["assertion_failure_verified"] is False
    assert receipt["passed"] is False
    assert receipt["errors"] >= 1


def test_certification_rejects_zero_collected_cases(tmp_path):
    test_file = tmp_path / "test_no_tests.py"
    test_file.write_text("ANSWER = 42\n", encoding="utf-8")
    receipt = EngineeringEvolutionWorker._run_trusted_regression(
        tmp_path, test_file.name, 35
    )
    assert receipt["tests"] == 0
    assert receipt["assertion_failure_verified"] is False
    assert receipt["passed"] is False
