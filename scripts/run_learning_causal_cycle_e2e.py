"""Ciclo causal de aprendizaje, de extremo a extremo y contra el runtime vivo.

No hay atajos: el saber nace de un mensaje por `POST /api/run`, lo extrae el
worker gobernado, lo mide el Measurement Core, se recupera en una conversación
posterior, se inyecta **antes** de generar y sólo cuenta como usado si el dato
aparece en la respuesta. Después se reinicia el proceso y se vuelve a preguntar.

Lo que separa esto de `run_learning_effectiveness_validation.py` es dónde ocurre:
allí se compara control/tratamiento sobre una copia, aquí se ejerce el camino de
producción entero, incluido el reinicio. Y de `run_knowledge_zero_to_one.py`, que
llama a las piezas directamente: aquí sólo se habla por HTTP, como un usuario.

Escribe en la base de producción a propósito —es la única forma de demostrar que
el circuito vivo funciona—, así que exige `--prod` explícito.

    python scripts/run_learning_causal_cycle_e2e.py --prod --marker OMEGA_5521
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

PROD = REPO / "triade/memory/triade.db"
BASE_URL = "http://127.0.0.1:8010"


def _plano(texto: str) -> str:
    limpio = unicodedata.normalize("NFKD", str(texto or ""))
    limpio = "".join(ch for ch in limpio if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", limpio.lower()).strip()


def _post(ruta: str, payload: dict[str, Any], timeout: int = 300) -> dict[str, Any]:
    import urllib.request

    datos = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}{ruta}", data=datos, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _get(ruta: str, timeout: int = 30) -> dict[str, Any]:
    import urllib.request

    with urllib.request.urlopen(f"{BASE_URL}{ruta}", timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{PROD}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _esperar(descripcion: str, prueba: Any, intentos: int = 60, espera: float = 5.0):
    """Espera a que el organismo haga su trabajo. No lo hace por él."""
    for i in range(intentos):
        valor = prueba()
        if valor:
            print(f"    · {descripcion}: OK tras {i * espera:.0f}s")
            return valor
        time.sleep(espera)
    print(f"    · {descripcion}: NO OCURRIÓ tras {intentos * espera:.0f}s")
    return None


def paso(n: int, titulo: str) -> None:
    print(f"\n[{n}] {titulo}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--prod", action="store_true", required=True)
    ap.add_argument("--marker", default="OMEGA_5521")
    ap.add_argument("--salida", default="artifacts/causal_cycle_e2e.json")
    args = ap.parse_args()

    marcador = args.marker
    # El dato tiene que ser imposible de adivinar: si el modelo puede acertarlo
    # sin el saber inyectado, la medición no mide nada. Es el mismo fallo que
    # contaminó 349 evidencias cuando el control ya traía la respuesta.
    ensenanza = (
        "Esta es una preferencia explícita del usuario: el código de cierre de "
        f"la auditoría de este ciclo es {marcador}."
    )
    pregunta = "¿Cuál es el código de cierre de la auditoría de este ciclo?"
    pregunta_ajena = "¿Cuántos planetas tiene el sistema solar?"
    informe: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "marker": marcador,
        "steps": {},
    }

    paso(1, "RUN A — una persona enseña un hecho por el camino de producción")
    run_a = _post("/api/run", {"text": ensenanza, "source": "react-ui"})
    run_a_id = run_a.get("run_id")
    tarea = (run_a.get("memory_diff") or {}).get("governed_learning_task") or {}
    print(f"    run_id={run_a_id}  aprendizaje_encolado={tarea.get('scheduled')}")
    informe["steps"]["run_a"] = {"run_id": run_a_id, "governed_learning_task": tarea}
    if not tarea.get("scheduled"):
        print("    ABORTA: el run no encoló aprendizaje gobernado.")
        return 1

    paso(2, "El worker extrae el candidato (nadie lo inserta a mano)")

    def _candidato():
        with _db() as c:
            f = c.execute(
                "SELECT candidate_id, status, source_type FROM learning_queue"
                " WHERE source_ref = ?",
                (f"run:{run_a_id}",),
            ).fetchone()
            return dict(f) if f else None

    cand = _esperar("candidato escrito", _candidato)
    if not cand:
        print("    ABORTA: el worker no produjo candidato.")
        return 1
    cid = cand["candidate_id"]
    print(
        f"    candidate_id={cid} status={cand['status']} fuente={cand['source_type']}"
    )
    informe["steps"]["candidate"] = cand

    paso(3, "Measurement Core: control vs tratamiento, por la cola de verdad")
    # Se encola el tipo de tarea real y lo ejecuta el worker que ya está
    # corriendo. Llamar a `LearningEvidenceProducer` a mano mediría lo mismo pero
    # demostraría menos: quedaría sin probar que la etapa es alcanzable sola.
    from triade.runtime.task_leases import AutonomousTaskStore

    AutonomousTaskStore(PROD).enqueue(
        "learning_evidence_generation",
        {"candidate_id": cid},
        idempotency_key=f"e2e-evidence:{cid}",
        priority=95,
    )

    def _evidencia():
        with _db() as c:
            f = c.execute(
                "SELECT decision, artifact_ref, comparison_json FROM learning_evidence"
                " WHERE candidate_id=?",
                (cid,),
            ).fetchone()
            return dict(f) if f and f["decision"] not in (None, "pending") else None

    evidencia = _esperar("evidencia medida", _evidencia, intentos=90, espera=10.0)
    if not evidencia:
        print("    ABORTA: la etapa de evidencia no produjo veredicto.")
        informe["verdict"] = "sin_evidencia"
        Path(args.salida).write_text(json.dumps(informe, indent=2, ensure_ascii=False))
        return 1
    decision = str(evidencia.get("decision") or "")
    print(f"    decision={decision}  artifact={evidencia.get('artifact_ref')}")
    informe["steps"]["evidence"] = evidencia
    if decision != "improved":
        print("    El gate no reconoce mejora. No se fuerza: se reporta y se sale.")
        informe["verdict"] = f"detenido_en_evidencia:{decision}"
        Path(args.salida).write_text(json.dumps(informe, indent=2, ensure_ascii=False))
        return 1

    def _promovido():
        with _db() as c:
            f = c.execute(
                "SELECT status FROM learning_queue WHERE candidate_id=?", (cid,)
            ).fetchone()
            return f["status"] if f and f["status"] != "internally_checked" else None

    estado = _esperar("promocion a evidence_verified", _promovido, intentos=30)
    print(f"    estado tras la medicion: {estado}")
    informe["steps"]["promotion"] = {"status": estado}

    paso(4, "Destino neuronal — lo encola el planner, no esta prueba")

    # Con `TRIADE_NEURAL_LEARNING_ROUTING=1` sólo un saber con ruta activa puede
    # acercarse al prompt. Se espera a que el organismo la cree por su cuenta:
    # forzarla aquí demostraría que la tabla admite filas, no que el circuito
    # las produce.
    def _ruta():
        with _db() as c:
            f = c.execute(
                "SELECT assignment_id, neuron_id, status FROM"
                " neuron_learning_assignments WHERE candidate_id=?",
                (cid,),
            ).fetchone()
            return dict(f) if f else None

    ruta = _esperar("ruta neuronal asignada", _ruta, intentos=60, espera=10.0)
    print(f"    ruta={ruta}")
    informe["steps"]["neural_route"] = ruta

    def _usos() -> int:
        with _db() as c:
            f = c.execute(
                "SELECT run_use_count FROM learning_queue WHERE candidate_id=?", (cid,)
            ).fetchone()
            return int(f["run_use_count"] or 0) if f else 0

    usos_antes = _usos()

    paso(5, "RUN B — se pregunta por el dato; debe recuperarse, inyectarse y usarse")
    run_b = _post("/api/run", {"text": pregunta, "source": "react-ui"})
    run_b_id = run_b.get("run_id")
    respuesta_b = str(run_b.get("response") or "")
    with _db() as c:
        dec = c.execute(
            "SELECT injected_ids, retrieved_ids, authorized_ids FROM"
            " learning_retrieval_decisions WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_b_id,),
        ).fetchone()
    inyectados = json.loads(dec["injected_ids"]) if dec and dec["injected_ids"] else []
    aparece = _plano(marcador) in _plano(respuesta_b)
    usos_despues = _usos()
    print(f"    run_id={run_b_id}")
    print(f"    inyectados={inyectados}")
    print(f"    marcador en la respuesta={aparece}")
    print(f"    run_use_count {usos_antes} -> {usos_despues}")
    print(f"    respuesta: {respuesta_b[:180]!r}")
    informe["steps"]["run_b"] = {
        "run_id": run_b_id,
        "injected_ids": inyectados,
        "marker_in_response": aparece,
        "run_use_count_before": usos_antes,
        "run_use_count_after": usos_despues,
        "response_excerpt": respuesta_b[:400],
    }

    paso(6, "CONTROL — una pregunta ajena no puede recuperar ni contar uso")
    run_c = _post("/api/run", {"text": pregunta_ajena, "source": "react-ui"})
    run_c_id = run_c.get("run_id")
    with _db() as c:
        dec_c = c.execute(
            "SELECT injected_ids FROM learning_retrieval_decisions"
            " WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_c_id,),
        ).fetchone()
    iny_c = json.loads(dec_c["injected_ids"]) if dec_c and dec_c["injected_ids"] else []
    usos_control = _usos()
    print(f"    inyectados={iny_c}  run_use_count={usos_control}")
    informe["steps"]["control"] = {
        "run_id": run_c_id,
        "injected_ids": iny_c,
        "run_use_count": usos_control,
        "contaminado": cid in iny_c,
    }

    paso(7, "Reinicio del proceso — el saber tiene que sobrevivir")
    subprocess.run(
        ["sudo", "-n", "systemctl", "restart", "triade-api"], check=False, timeout=120
    )
    for _ in range(60):
        try:
            if _get("/health/live").get("status") == "alive":
                break
        except OSError as exc:
            # El arranque tarda; se reintenta. Se dice en voz alta porque un
            # bucle de espera mudo esconde un runtime que no vuelve.
            print(f"    esperando al runtime: {type(exc).__name__}")
        time.sleep(5)
    print("    runtime de nuevo vivo")

    paso(8, "RUN D — tras el reinicio, se vuelve a preguntar")
    run_d = _post("/api/run", {"text": pregunta, "source": "react-ui"})
    run_d_id = run_d.get("run_id")
    respuesta_d = str(run_d.get("response") or "")
    with _db() as c:
        dec_d = c.execute(
            "SELECT injected_ids FROM learning_retrieval_decisions"
            " WHERE run_id=? ORDER BY id DESC LIMIT 1",
            (run_d_id,),
        ).fetchone()
    iny_d = json.loads(dec_d["injected_ids"]) if dec_d and dec_d["injected_ids"] else []
    aparece_d = _plano(marcador) in _plano(respuesta_d)
    with _db() as c:
        final = dict(
            c.execute(
                "SELECT status, run_use_count, avg_outcome_score FROM learning_queue"
                " WHERE candidate_id=?",
                (cid,),
            ).fetchone()
        )
    print(f"    inyectados={iny_d}  marcador en la respuesta={aparece_d}")
    print(f"    estado final del candidato: {final}")
    informe["steps"]["run_d_post_restart"] = {
        "run_id": run_d_id,
        "injected_ids": iny_d,
        "marker_in_response": aparece_d,
        "response_excerpt": respuesta_d[:400],
    }
    informe["steps"]["final_state"] = final

    informe["verdict"] = {
        "candidato_de_conversacion_real": True,
        "evidencia_improved": decision == "improved",
        "inyectado_antes_de_generar": cid in inyectados,
        "uso_causal_confirmado": usos_despues > usos_antes,
        "ruta_neuronal_automatica": bool(ruta),
        "control_limpio": cid not in iny_c and usos_control == usos_despues,
        "sobrevive_al_reinicio": cid in iny_d,
    }
    print("\n=== VEREDICTO ===")
    for k, v in informe["verdict"].items():
        print(f"  {k}: {v}")
    Path(args.salida).parent.mkdir(parents=True, exist_ok=True)
    Path(args.salida).write_text(json.dumps(informe, indent=2, ensure_ascii=False))
    print(f"\ninforme -> {args.salida}")
    return 0 if all(informe["verdict"].values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
