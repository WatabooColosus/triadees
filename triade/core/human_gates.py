"""Qué está esperando una firma humana, y si de verdad podría aceptarla.

Existe porque las compuertas humanas estaban repartidas y sólo una se veía. El
adaptador PEFT tenía su tarjeta en Cabina Viva; la aprobación de una propuesta
de auto-mejora sólo existía como ruta HTTP, sin ningún sitio donde apareciera
que estaba esperando. Una compuerta que nadie ve no gobierna nada: deja el
circuito parado y con aspecto de estar funcionando.

Dos reglas gobiernan este módulo:

- **No decide nada.** Sólo lee y describe. Aprobar sigue siendo una llamada
  explícita con un nombre propio detrás, en el endpoint de cada subsistema.
- **Dice también por qué NO se puede firmar.** Es la parte que faltaba. El
  canary PEFT de la base viva lleva desde el 2026-07-29 acumulando
  observaciones —305 al 27-ago, una cada veinte o cuarenta minutos, catorce
  segundos de inferencia cada una— y `activate()` lo habría rechazado igual
  cualquiera de esos días: se inscribió antes de que existiera la columna
  `base_model`, la tiene vacía, y `_served_matching("")` no casa con ningún
  modelo servido. Sin esto, quien mira la Cabina ve «listo para aprobar» y
  descubre el bloqueo al firmar.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from triade.db import sqlite3

DEFAULT_DB_PATH = "triade/memory/triade.db"


def _tabla(conn: sqlite3.Connection, nombre: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (nombre,)
        ).fetchone()
        is not None
    )


def _modelos_servidos() -> list[str]:
    """Lo que Ollama sirve ahora mismo, no lo que la configuración promete."""
    try:
        from triade.models.ollama_client import OllamaClient

        return [str(m) for m in (OllamaClient().health().get("models") or [])]
    except (OSError, ImportError, RuntimeError, ValueError, TypeError, KeyError):
        return []


def base_model_del_manifiesto(adapter_path: str) -> str:
    """El modelo base que declara el artefacto en disco.

    Una versión inscrita antes de que existiera la columna `base_model` la tiene
    vacía en la base, pero su manifiesto sí lo dice. Leerlo de ahí no inventa
    nada: es el mismo dato que `enroll()` exige hoy.
    """
    if not adapter_path:
        return ""
    manifiesto = Path(adapter_path) / "triade_adapter_manifest.json"
    try:
        datos = json.loads(manifiesto.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(datos.get("base_model") or "").strip()


def _base_model_servido(base_model: str) -> bool:
    if not base_model:
        return False
    from triade.training.serving_governance import normalize_model_id

    clave = normalize_model_id(base_model)
    if not clave:
        return False
    return any(normalize_model_id(m) == clave for m in _modelos_servidos())


def _peft_gates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _tabla(conn, "governed_peft_versions"):
        return []
    filas = conn.execute(
        "SELECT version_id, adapter_path, base_model, traffic_percent, created_at "
        "FROM governed_peft_versions WHERE status = 'canary' ORDER BY created_at"
    ).fetchall()
    salida: list[dict[str, Any]] = []
    for fila in filas:
        observaciones = 0
        if _tabla(conn, "governed_peft_observations"):
            observaciones = int(
                conn.execute(
                    "SELECT COUNT(*) FROM governed_peft_observations "
                    "WHERE version_id = ? AND success = 1",
                    (fila["version_id"],),
                ).fetchone()[0]
            )
        bloqueos: list[str] = []
        # Las mismas condiciones que `GovernedPeftServing.activate()`, leídas
        # antes de firmar en vez de después. Duplicarlas sería arriesgado —dos
        # criterios acaban divergiendo—, así que aquí sólo se comprueba lo que
        # se puede saber sin tocar Ollama, y el veredicto final sigue siendo del
        # propio `activate()`.
        if observaciones < 1:
            bloqueos.append("sin una sola observación con éxito")
        base = str(fila["base_model"] or "").strip() or base_model_del_manifiesto(
            str(fila["adapter_path"] or "")
        )
        servido = _base_model_servido(base)
        if not base:
            bloqueos.append(
                "la versión no declara `base_model` y su manifiesto tampoco: "
                "`activate()` la rechazará por `base_model_not_served`"
            )
        elif not servido:
            # El motivo de verdad, y no es cosmético. El adaptador de la base
            # viva se entrenó sobre `Qwen/Qwen2.5-0.5B-Instruct` mientras el
            # runtime sirve `qwen2.5:3b-instruct`: son familias distintas y
            # aplicarlo no serviría de nada. La verja hace bien en bloquearlo
            # —lo dice `activate()`: un adaptador sobre un modelo que nadie
            # sirve dejaría el slot de producción apuntando a algo inservible, y
            # con firma humana encima—. Lo que faltaba era decirlo.
            bloqueos.append(
                f"entrenado sobre `{base}`, que el runtime no sirve "
                f"(sirve: {', '.join(_modelos_servidos()) or 'nada'}). "
                "No es un fallo de la verja: el adaptador no se puede aplicar"
            )
        salida.append(
            {
                "kind": "peft_activation",
                "id": str(fila["version_id"]),
                "title": "Adaptador LoRA en canary esperando activación",
                "detail": (
                    f"{observaciones} observaciones con éxito al "
                    f"{fila['traffic_percent']}% de tráfico"
                ),
                "since": str(fila["created_at"] or ""),
                "endpoint": "/api/governance/peft/activate",
                "payload_hint": {
                    "adapter_path": str(fila["adapter_path"] or ""),
                    "approved_by": "<tu nombre>",
                },
                "ready": not bloqueos,
                "blockers": bloqueos,
            }
        )
    return salida


def _improvement_gates(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not _tabla(conn, "improvement_proposals"):
        return []
    from triade.self_improvement.auto_approval import decide_for_proposal

    filas = conn.execute(
        "SELECT proposal_id, signal_id, payload_json, created_at "
        "FROM improvement_proposals WHERE status = 'open' ORDER BY rowid"
    ).fetchall()
    salida: list[dict[str, Any]] = []
    for fila in filas:
        try:
            payload = json.loads(fila["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        decision = decide_for_proposal(conn, str(fila["proposal_id"]))
        bloqueos: list[str] = []
        # Sin destino la propuesta se aprueba y muere en el handler, así que
        # firmarla no serviría de nada. Decirlo aquí evita una firma inútil.
        if not (payload.get("neuron_id") and payload.get("version")):
            bloqueos.append(
                "la propuesta no declara neurona destino (neuron_id/version): "
                "aprobarla no la haría avanzar"
            )
        salida.append(
            {
                "kind": "improvement_proposal",
                "id": str(fila["proposal_id"]),
                "title": "Propuesta de auto-mejora esperando aprobación",
                "detail": str(payload.get("hypothesis") or "")[:280],
                "since": str(fila["created_at"] or ""),
                "endpoint": (
                    f"/api/governance/improvement/proposals/"
                    f"{fila['proposal_id']}/approve"
                ),
                "payload_hint": {"approved_by": "<tu nombre>"},
                # La política puede aprobarla sola; se dice para que quien mira
                # sepa si su firma hace falta o sólo adelanta lo inevitable.
                "policy_would_approve": decision.allowed,
                "policy_reason": decision.reason,
                "ready": not bloqueos,
                "blockers": bloqueos,
            }
        )
    return salida


def pending_human_gates(db_path: str | Path = DEFAULT_DB_PATH) -> dict[str, Any]:
    """Todo lo que espera una firma, con su estado real. No cambia nada."""
    ruta = Path(db_path)
    if not ruta.exists():
        return {"count": 0, "gates": [], "detail": "sin base viva"}
    conn = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        gates = _peft_gates(conn) + _improvement_gates(conn)
    except sqlite3.Error as exc:
        return {"count": 0, "gates": [], "error": f"{type(exc).__name__}: {exc}"}
    finally:
        conn.close()
    return {
        "count": len(gates),
        "ready": sum(1 for g in gates if g["ready"]),
        "blocked": sum(1 for g in gates if not g["ready"]),
        "gates": gates,
        "policy": "leer no aprueba: firmar es una llamada explícita con nombre",
    }
