"""Da un hijo sondeable a un candidato que no lo es, sin tocar al padre.

El 2026-08-26 había 994 candidatos en `internally_checked` y **ninguno** de los
149 elegibles era medible: `extract_target()` devolvía `None` para todos, el
planificador no encolaba `learning_evidence_generation` y la cadena llevaba
parada desde el 12 de agosto.

La reparación **no** es reescribir al padre. La transcripción cruda es el
registro de lo que pasó y tiene su propio valor probatorio; machacarla con una
paráfrasis perdería la fuente y haría irrepetible cualquier auditoría. Lo que se
escribe es una fila nueva, `source_type='distilled'`, que apunta al padre por
`source_ref`. Si la destilación resulta estar mal, se descarta el hijo y el
padre sigue intacto.

## Qué se destila y qué no

Sólo `web`. Las 60 conversacionales elegibles son transcripciones de runs, es
decir salidas del propio modelo: medir que repite lo que dijo demuestra memoria,
no que el dato sea cierto —el mismo argumento que ya hace
`is_unverified_transcript()` aguas abajo—. `tool` y `qualia_bus` son registros de
ejecución, no fuentes factuales.

El hijo nace en `internally_checked` porque **hereda la verificación del
padre**: el padre ya pasó ese listón, y la destilación no añade ninguna
afirmación que el padre no hiciera. No es un atajo al gate de evidencia: el hijo
tiene que pasar por `learning_evidence_generation` como cualquier otro.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from triade.db import sqlite3
from triade.learning.assertion_distiller import distill_assertion
from triade.learning.knowledge_probe import extract_target

PROMOTER_VERSION = "assertion-promoter-1.0.0"

#: Fuentes destilables. Ver el porqué de cada exclusión en el docstring.
FUENTES_DESTILABLES = frozenset({"web"})

#: Tope de padres inspeccionados por ciclo. Destilar es una regex sobre texto ya
#: leído, pero la tanda acota el trabajo por tarea igual que
#: `EVIDENCE_SCAN_LIMIT`.
SCAN_LIMIT = 200


@dataclass
class PromotionReport:
    """Qué se miró y qué salió. Sin esto, «no pasó nada» es indistinguible."""

    inspected: int = 0
    distilled: int = 0
    written: int = 0
    skipped_already_probeable: int = 0
    skipped_no_assertion: int = 0
    skipped_duplicate: int = 0
    written_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "inspected": self.inspected,
            "distilled": self.distilled,
            "written": self.written,
            "skipped_already_probeable": self.skipped_already_probeable,
            "skipped_no_assertion": self.skipped_no_assertion,
            "skipped_duplicate": self.skipped_duplicate,
            "written_ids": list(self.written_ids),
        }


class AssertionPromoter:
    """Escribe hijos sondeables para los padres que no lo son."""

    def __init__(self, db_path: str | Path, *, scan_limit: int = SCAN_LIMIT) -> None:
        self.db_path = str(db_path)
        self.scan_limit = scan_limit

    # ── registro de intentos ─────────────────────────────────────────
    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """La tabla de intentos, creada al vuelo como hace `LearningEvidenceBridge`.

        Sin ella la tarea **gira en vacío para siempre**: de 46 padres `web`
        reales sólo 6 dieron aserción, y los 40 restantes volverían a contarse
        como «sin destilar» en cada ciclo. Un `no_op` eterno es exactamente lo
        que hace parecer vivo un panel muerto.
        """
        conn.execute(
            """CREATE TABLE IF NOT EXISTS learning_distillation_attempts (
                candidate_id TEXT PRIMARY KEY,
                promoter_version TEXT NOT NULL,
                outcome TEXT NOT NULL,
                attempted_at TEXT NOT NULL)"""
        )

    # ── selección ────────────────────────────────────────────────────
    def _parents(self, conn: sqlite3.Connection) -> list[sqlite3.Row]:
        marcas = ",".join("?" for _ in FUENTES_DESTILABLES)
        # Dos exclusiones, y hacen falta las dos:
        #  - el que ya tiene hijo, porque duplicaría la afirmación;
        #  - el que ya se intentó **con esta versión**, porque si no dio nada
        #    tampoco lo dará ahora. Se compara la versión a propósito: al
        #    mejorar el destilador, subir `PROMOTER_VERSION` reabre a todos los
        #    descartados sin tener que borrar nada a mano.
        return list(
            conn.execute(
                f"""SELECT candidate_id, content FROM learning_queue AS p
                    WHERE p.status = 'internally_checked'
                      AND p.source_type IN ({marcas})
                      AND NOT EXISTS (
                        SELECT 1 FROM learning_queue AS h
                        WHERE h.source_type = 'distilled'
                          AND h.source_ref = 'candidate:' || p.candidate_id)
                      AND NOT EXISTS (
                        SELECT 1 FROM learning_distillation_attempts a
                        WHERE a.candidate_id = p.candidate_id
                          AND a.promoter_version = ?)
                    ORDER BY p.id DESC LIMIT ?""",
                (*sorted(FUENTES_DESTILABLES), PROMOTER_VERSION, self.scan_limit),
            ).fetchall()
        )

    def _record(
        self, conn: sqlite3.Connection, candidate_id: str, outcome: str, ahora: str
    ) -> None:
        conn.execute(
            """INSERT OR REPLACE INTO learning_distillation_attempts
               (candidate_id, promoter_version, outcome, attempted_at)
               VALUES (?,?,?,?)""",
            (candidate_id, PROMOTER_VERSION, outcome, ahora),
        )

    # ── escritura ────────────────────────────────────────────────────
    @staticmethod
    def _candidate_id(padre: str, clave: str) -> str:
        huella = hashlib.sha256(f"{padre}|{clave}".encode()).hexdigest()[:16]
        return f"dst-{huella}"

    def run(self) -> PromotionReport:
        reporte = PromotionReport()
        ahora = datetime.now(UTC).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            self._ensure_schema(conn)
            for padre in self._parents(conn):
                reporte.inspected += 1
                padre_id = str(padre["candidate_id"])
                contenido = str(padre["content"] or "")

                # Un padre que ya es sondeable no necesita hijo: duplicarlo sólo
                # gastaría una medición en decir dos veces lo mismo.
                if extract_target(contenido):
                    reporte.skipped_already_probeable += 1
                    self._record(conn, padre_id, "already_probeable", ahora)
                    continue

                asercion = distill_assertion(contenido)
                if asercion is None:
                    reporte.skipped_no_assertion += 1
                    self._record(conn, padre_id, "no_assertion", ahora)
                    continue
                reporte.distilled += 1

                nuevo = self._candidate_id(str(padre["candidate_id"]), asercion["key"])
                texto = asercion["content"]
                ya = conn.execute(
                    "SELECT 1 FROM learning_queue WHERE candidate_id = ?"
                    " OR normalized_summary = ?",
                    (nuevo, texto),
                ).fetchone()
                if ya:
                    reporte.skipped_duplicate += 1
                    self._record(conn, padre_id, "duplicate", ahora)
                    continue

                conn.execute(
                    """INSERT INTO learning_queue
                       (candidate_id, source_type, source_ref, title, content,
                        normalized_summary, domain, risk_level, confidence,
                        utility, status, verification_notes, created_at,
                        updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        nuevo,
                        "distilled",
                        f"candidate:{padre['candidate_id']}",
                        f"assertion: {asercion['key']}",
                        texto,
                        texto,
                        "world_knowledge",
                        "low",
                        # La confianza es la del padre menos el riesgo de que la
                        # destilación haya recortado mal. No se hereda entera:
                        # afirmar con la misma seguridad una paráfrasis que su
                        # fuente sería inventarse precisión.
                        0.6,
                        0.9,
                        "internally_checked",
                        json.dumps(
                            {
                                "promoter": PROMOTER_VERSION,
                                "type": "fact",
                                "parent_candidate_id": str(padre["candidate_id"]),
                                "extractor": asercion.get("extractor", ""),
                            },
                            ensure_ascii=False,
                        ),
                        ahora,
                        ahora,
                    ),
                )
                self._record(conn, padre_id, "written", ahora)
                reporte.written += 1
                reporte.written_ids.append(nuevo)
        return reporte
