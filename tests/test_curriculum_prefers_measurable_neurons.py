"""Educar a una neurona que nadie puede medir es trabajo perdido.

Auditoría 2026-08-02, P1-05. El circuito de educación neuronal quedó completo y
verificado sobre copia real, y aun así no podía cerrarse en producción: las
7 sesiones en `lesson_prepared` eran de las neuronas 11 y 12, que **sólo se
activan en runs `pulse-*`** — y esos runs no generan `verification_reports`. La
neurona 6471, con 63 runs medibles, nunca llegaba a `lesson_prepared`.

La causa está en `_target()`: ordenaba por `retention_score ASC, n.id ASC`, así
que siempre ganaba la experimental de menor id. Las 11 y 12 tienen los ids más
bajos, y se llevaban todos los ciclos.

No falta productor ni consumidor. Falta que se crucen.

**Se prioriza, no se excluye.** Dejar fuera para siempre a una neurona no
evaluable sería otra decisión silenciosa: si nadie más tiene trabajo pendiente,
se la sigue educando. Lo que cambia es el orden, no el derecho.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from triade.neurons.education_cycle import NeuronEducationCycle

# `CompetencyStore` aplica sus migraciones al construirse, asi que aqui solo se
# crean las tablas que NO son suyas. El esquema de `neurons` se copia del real,
# incluidos los NOT NULL: uno mas permisivo deja pasar fallos que solo aparecen
# contra la base de verdad.
ESQUEMA = """
CREATE TABLE neurons (
    id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
    mission TEXT NOT NULL, domain TEXT, status TEXT DEFAULT 'candidate',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE neuron_missions (id INTEGER PRIMARY KEY, neuron_id INTEGER);
CREATE TABLE neuron_activity (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, neuron_id INTEGER,
    activated INTEGER, created_at TEXT);
CREATE TABLE verification_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, coherence_score REAL,
    created_at TEXT);
"""

#: Id bajo, sin runs medibles: la que ganaba siempre.
INVISIBLE = 11
#: Id alto, con runs medibles: la que nunca era elegida.
MEDIBLE = 6471


def _db(tmp_path: Path, *, medible_activa: bool = True) -> Path:
    ruta = tmp_path / "triade.db"
    with sqlite3.connect(ruta) as conn:
        conn.executescript(ESQUEMA)
        conn.executemany(
            "INSERT INTO neurons (id,name,domain,mission,status) VALUES (?,?,?,?,?)",
            [
                (INVISIBLE, "Neurona Visual", "vision", "ver", "experimental"),
                (MEDIBLE, "Neurona Medible", "conversation", "hablar", "experimental"),
            ],
        )
        # La invisible sólo aparece en runs de pulso, que no llevan informe.
        conn.execute(
            "INSERT INTO neuron_activity (run_id,neuron_id,activated,created_at) "
            "VALUES ('pulse-1',?,1,'2026-07-29 02:00:00')",
            (INVISIBLE,),
        )
        if medible_activa:
            for i in range(3):
                conn.execute(
                    "INSERT INTO neuron_activity (run_id,neuron_id,activated,"
                    "created_at) VALUES (?,?,1,'2026-08-01 10:00:00')",
                    (f"run-{i}", MEDIBLE),
                )
                conn.execute(
                    "INSERT INTO verification_reports (run_id,coherence_score,"
                    "created_at) VALUES (?,0.85,'2026-08-01 10:00:00')",
                    (f"run-{i}",),
                )
        conn.commit()
    # Construir el ciclo aplica las migraciones del `CompetencyStore`, que son
    # las duenas de `neuron_competencies`. Crearla a mano aqui la duplicaria.
    NeuronEducationCycle(ruta)
    return ruta


def _elegida(db: Path) -> int | None:
    objetivo = NeuronEducationCycle(db)._target()
    return None if objetivo is None else int(objetivo["id"])


class TestPrefiereLoMedible:
    def test_elige_la_neurona_con_runs_medibles(self, tmp_path: Path) -> None:
        """Aunque tenga el id más alto."""
        db = _db(tmp_path)

        assert _elegida(db) == MEDIBLE, (
            "eligió una neurona sin runs medibles: su lección nunca podrá "
            "evaluarse y el ciclo se queda en insufficient_evidence"
        )

    def test_la_actividad_sin_informe_no_hace_medible(self, tmp_path: Path) -> None:
        """Activarse en `pulse-*` no es ser evaluable."""
        db = _db(tmp_path, medible_activa=False)

        # Sin nadie medible, se sigue educando a la que hay: prioriza, no excluye.
        assert _elegida(db) == INVISIBLE


class TestNoExcluye:
    def test_sin_medibles_sigue_habiendo_objetivo(self, tmp_path: Path) -> None:
        """Priorizar no puede dejar el ciclo sin trabajo."""
        db = _db(tmp_path, medible_activa=False)
        assert _elegida(db) is not None

    def test_la_retencion_sigue_pesando_entre_medibles(self, tmp_path: Path) -> None:
        """Dentro de las evaluables, sigue mandando la que peor retiene."""
        db = _db(tmp_path)
        with sqlite3.connect(db) as conn:
            conn.execute(
                "INSERT INTO neurons (id,name,domain,mission,status) "
                "VALUES (7000,'Otra Medible','conversation','x','experimental')"
            )
            for i in range(3):
                conn.execute(
                    "INSERT INTO neuron_activity (run_id,neuron_id,activated,"
                    "created_at) VALUES (?,7000,1,'2026-08-01 10:00:00')",
                    (f"otro-{i}",),
                )
                conn.execute(
                    "INSERT INTO verification_reports (run_id,coherence_score,"
                    "created_at) VALUES (?,0.85,'2026-08-01 10:00:00')",
                    (f"otro-{i}",),
                )
            # La 7000 retiene peor: debe ir antes que la 6471.
            conn.execute(
                "INSERT INTO neuron_competencies (competency_id,neuron_id,domain,"
                "name,retention_score,next_review,created_at,updated_at) VALUES "
                "('c1',7000,'conversation','x',0.1,NULL,'2026-08-01','2026-08-01')"
            )
            conn.execute(
                "INSERT INTO neuron_competencies (competency_id,neuron_id,domain,"
                "name,retention_score,next_review,created_at,updated_at) VALUES "
                "('c2',?,'conversation','x',0.9,NULL,'2026-08-01','2026-08-01')",
                (MEDIBLE,),
            )
            conn.commit()

        assert _elegida(db) == 7000


class TestNoRevienta:
    def test_sin_tablas_de_medicion(self, tmp_path: Path) -> None:
        """En una base recién migrada puede no haber actividad ni informes."""
        ruta = tmp_path / "minima.db"
        with sqlite3.connect(ruta) as conn:
            conn.executescript(ESQUEMA)
            conn.execute(
                "INSERT INTO neurons (id,name,domain,mission,status) "
                "VALUES (1,'Sola','x','y','experimental')"
            )
            conn.commit()

        assert _elegida(ruta) == 1

    def test_sin_neuronas_experimentales(self, tmp_path: Path) -> None:
        ruta = tmp_path / "vacia.db"
        with sqlite3.connect(ruta) as conn:
            conn.executescript(ESQUEMA)
            conn.commit()

        assert _elegida(ruta) is None
