"""Aprender del fallo y compartirlo entre neuronas.

Fija por contrato los dos huecos que el responsable señaló (2026-07-31):

    "Si falla porque no pasa el umbral no existe algo para que aprenda sobre eso
     y mejore la forma de aprender en eso que falló hasta pasar el umbral."

    "Así mismo la interconexión entre neuronas ayuda a todas y al sistema Tríade."

Antes de `failure_learning.py`, `quarantined` era terminal y **nadie en
producción creaba una `ImprovementSignal`**: el ciclo podía verificar con rigor
pero no tenía cómo arrancar solo ni cómo aprender de lo que reprobó.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from triade.neuron_factory import (
    NeuronSpecification,
    NeuronSpecificationStore,
    ResourceBudget,
)
from triade.self_improvement.failure_learning import (
    MAX_ATTEMPTS,
    FailureLearningLoop,
)
from triade.workers.worker_loop import WorkerLoop

CAP = "triade_vitality"


def _reprobar(
    db: Path,
    report_id: str,
    *,
    candidate_id: str = "cand",
    metric: str = "coherence",
    severity: str = "high",
    baseline: float = 0.90,
    candidate: float = 0.74,
    tambien_pasa: bool = True,
) -> None:
    """Escribe un informe de regresión reprobado igual que lo hace el gate."""
    findings = [
        {
            "metric_id": metric,
            "severity": severity,
            "baseline_score": baseline,
            "candidate_score": candidate,
            "absolute_delta": candidate - baseline,
            "status": "fail",
            "reason": f"caída de {baseline - candidate:.3f}",
        }
    ]
    if tambien_pasa:
        findings.append(
            {
                "metric_id": "memory",
                "severity": "high",
                "baseline_score": 0.90,
                "candidate_score": 0.91,
                "absolute_delta": 0.01,
                "status": "pass",
                "reason": "sin regresión",
            }
        )
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS regression_reports (
                report_id TEXT, candidate_id TEXT, capability TEXT,
                decision TEXT, findings_json TEXT)"""
        )
        conn.execute(
            "INSERT INTO regression_reports VALUES (?,?,?,?,?)",
            (report_id, candidate_id, CAP, "fail", json.dumps(findings)),
        )


# ── El fallo enseña: se vuelve el intento siguiente ────────────────────


def test_una_cuarentena_produce_una_senal_dirigida(tmp_path: Path):
    """La señal apunta a la métrica que falló, con la brecha real medida."""
    db = tmp_path / "t.db"
    loop = FailureLearningLoop(db)
    _reprobar(db, "r1")
    result = loop.harvest()

    assert result["signals_created"] == 1
    signal = result["signals"][0]
    assert signal["metric_id"] == "coherence"
    # `memory` pasó: no genera señal. Solo se aprende de lo que realmente falló.
    assert all(s["metric_id"] != "memory" for s in result["signals"])

    stored = json.loads(
        sqlite3.connect(db)
        .execute(
            "SELECT payload_json FROM improvement_signals WHERE signal_id = ?",
            (signal["signal_id"],),
        )
        .fetchone()[0]
    )
    # No se inventa el objetivo: observado = lo logrado, objetivo = el listón.
    assert stored["observed_score"] == 0.74
    assert stored["target_score"] == 0.90
    assert stored["source_ref"] == "regression_report:r1"


def test_learning_evidence_regression_is_wired_to_failure_learning() -> None:
    """La regresión causal debe cosecharse donde nace, no tras otro ciclo."""
    source = __import__("inspect").getsource(WorkerLoop._learning_evidence_generation)
    assert 'outcome.decision == "regressed"' in source
    assert "FailureLearningLoop(self.db_path).harvest(limit=1)" in source

    review_source = __import__("inspect").getsource(WorkerLoop._pending_learning_review)
    assert "FailureLearningLoop(self.db_path).harvest(limit=5)" in review_source


def test_la_hipotesis_siguiente_incorpora_lo_ya_fallado(tmp_path: Path):
    """No repite a ciegas: el intento siguiente sabe qué se intentó antes."""
    db = tmp_path / "t.db"
    loop = FailureLearningLoop(db)
    assert "recuperar coherence" in loop.hypothesis_for(CAP, "coherence")

    _reprobar(db, "r1")
    loop.harvest()
    hypothesis = loop.hypothesis_for(CAP, "coherence")
    assert "enfoque distinto" in hypothesis
    assert "0.7400" in hypothesis


def test_cosechar_dos_veces_no_duplica(tmp_path: Path):
    db = tmp_path / "t.db"
    loop = FailureLearningLoop(db)
    _reprobar(db, "r1")
    assert loop.harvest()["signals_created"] == 1
    assert loop.harvest()["signals_created"] == 0
    assert loop.attempts_for(CAP, "coherence") == 1


def test_cada_fallo_afila_la_misma_senal_en_vez_de_apilar_duplicados(tmp_path: Path):
    """La brecha es una sola; cada fallo la mide mejor y sube su coste.

    Sin esto la señal abierta quedaría congelada en el primer intento y la
    escalada (coste mayor, confianza menor) nunca surtiría efecto.
    """
    db = tmp_path / "t.db"
    loop = FailureLearningLoop(db)
    prioridades = []
    for i in range(1, 4):
        _reprobar(db, f"r{i}", candidate_id=f"c{i}")
        for signal in loop.harvest(limit=20)["signals"]:
            prioridades.append(signal["priority"])

    assert len(prioridades) == 3
    assert prioridades == sorted(prioridades, reverse=True), prioridades
    total = (
        sqlite3.connect(db)
        .execute("SELECT COUNT(*) FROM improvement_signals")
        .fetchone()[0]
    )
    assert total == 1


def test_una_metrica_inalcanzable_cede_el_turno_sola(tmp_path: Path):
    """Sin humano y sin bucle infinito: se agota y deja de consumir ciclos."""
    db = tmp_path / "t.db"
    loop = FailureLearningLoop(db)
    agotado = False
    for i in range(1, MAX_ATTEMPTS + 2):
        _reprobar(db, f"r{i}", candidate_id=f"c{i}")
        result = loop.harvest(limit=30)
        if result["exhausted"]:
            agotado = True
            assert result["exhausted"][0]["attempt"] == MAX_ATTEMPTS + 1
    assert agotado


def test_sin_puntuaciones_no_adivina(tmp_path: Path):
    """Archiva la lección, pero no fabrica un objetivo que no midió."""
    db = tmp_path / "t.db"
    loop = FailureLearningLoop(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS regression_reports (
                report_id TEXT, candidate_id TEXT, capability TEXT,
                decision TEXT, findings_json TEXT)"""
        )
        conn.execute(
            "INSERT INTO regression_reports VALUES (?,?,?,?,?)",
            (
                "r-nulo",
                "c",
                CAP,
                "fail",
                json.dumps(
                    [
                        {
                            "metric_id": "coherence",
                            "severity": "high",
                            "baseline_score": None,
                            "candidate_score": None,
                            "absolute_delta": None,
                            "status": "fail",
                            "reason": "sin evaluación",
                        }
                    ]
                ),
            ),
        )
    result = loop.harvest()
    assert result["signals_created"] == 0
    assert result["lessons_recorded"] == 1
    # No se descarta en silencio: queda el motivo.
    assert result["skipped"][0]["reason_skipped"] == "sin puntuaciones"


def test_el_ruido_de_coma_flotante_no_genera_senal(tmp_path: Path):
    db = tmp_path / "t.db"
    loop = FailureLearningLoop(db)
    _reprobar(db, "r-ruido", baseline=0.90, candidate=0.90 - 1e-12)
    result = loop.harvest()
    assert result["signals_created"] == 0
    assert result["skipped"][0]["reason_skipped"] == "brecha no significativa"


def test_un_informe_aprobado_no_genera_nada(tmp_path: Path):
    """Solo se aprende de lo reprobado; un pase no abre trabajo inventado."""
    db = tmp_path / "t.db"
    loop = FailureLearningLoop(db)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS regression_reports (
                report_id TEXT, candidate_id TEXT, capability TEXT,
                decision TEXT, findings_json TEXT)"""
        )
        conn.execute(
            "INSERT INTO regression_reports VALUES (?,?,?,?,?)",
            ("r-ok", "c", CAP, "pass", json.dumps([])),
        )
    assert loop.harvest()["reports_seen"] == 0


def test_base_sin_tablas_no_revienta(tmp_path: Path):
    """Un worker no puede caerse porque la base todavía esté vacía."""
    loop = FailureLearningLoop(tmp_path / "vacia.db")
    assert loop.harvest()["reports_seen"] == 0
    assert loop.lessons_for(CAP, "coherence") == []
    assert loop.affected_neurons(CAP) == {"provides": [], "requires": []}


# ── La interconexión: lo aprendido por una sirve a todas ───────────────


def _spec(neuron_id: str, provides: tuple[str, ...], requires: tuple[str, ...]):
    return NeuronSpecification(
        neuron_id=neuron_id,
        name=neuron_id,
        mission="misión de prueba",
        domain=CAP,
        version="1.0.0",
        owner="central",
        component=f"triade.neurons.{neuron_id}",
        input_contract={"type": "object"},
        output_contract={"type": "object"},
        provides_capabilities=provides,
        requires_capabilities=requires,
        training_policy="configuration",
        resource_budget=ResourceBudget(1024, 300, 1),
    )


def test_la_leccion_es_de_la_capacidad_no_de_la_neurona(tmp_path: Path):
    """Una neurona nueva hereda el fallo de otra sin tener que repetirlo.

    Es el punto exacto de la interconexión: el historial se indexa por
    `(capacidad, métrica)`, así que quien trabaje esa capacidad después arranca
    sabiendo lo que ya no funcionó.
    """
    db = tmp_path / "t.db"
    loop = FailureLearningLoop(db)
    _reprobar(db, "r1", candidate_id="neurona-A")
    loop.harvest()

    lecciones = loop.lessons_for(CAP, "coherence")
    assert [item["candidate_id"] for item in lecciones] == ["neurona-A"]
    # Una neurona distinta consulta la MISMA lección: no parte de cero.
    assert loop.attempts_for(CAP, "coherence") == 1
    assert "0.7400" in loop.hypothesis_for(CAP, "coherence")


def test_un_fallo_local_identifica_a_las_neuronas_dependientes(tmp_path: Path):
    """Quien provee la capacidad y quién queda degradado si cae."""
    db = tmp_path / "t.db"
    store = NeuronSpecificationStore(db)
    store.register(_spec("neuron.provee", (CAP,), ("identity_core",)))
    store.register(_spec("neuron.depende", ("otra_cosa",), (CAP,)))
    store.register(_spec("neuron.ajena", ("nada_que_ver",), ("identity_core",)))

    afectadas = FailureLearningLoop(db).affected_neurons(CAP)
    assert afectadas["provides"] == ["neuron.provee"]
    assert afectadas["requires"] == ["neuron.depende"]
