"""Cada neurona aprende sus propias palabras de activación. Con un límite.

El problema medido (auditoría 2026-07-31): `Neurona Visual` y `Neurona de Código
y Reparación` llevaban **0 activaciones reales en 35 pulsos**, mientras
`neurona-llamo-santiago-wataboo-creador` acumulaba 43 — porque el enrutado caía
en un fallback que activa la neurona si un trozo de su *nombre* aparece en el
texto, y su nombre está hecho de palabras de conversación.

La solución obvia sería que alguien escribiera a mano los `triggers` de cada
neurona. Pero entonces una neurona nueva nace muda hasta que un humano se acuerde
de ella, y el sistema deja de poder crecer solo.

Por qué esto no es dejar que se conceda tráfico
-----------------------------------------------
Una neurona que escribe sus propios triggers **puede ampliarse el alcance sin
permiso**. Eso es exactamente la deriva que este runtime existe para impedir.

Así que no se le permite inventar: solo puede **leer su propia carta**. Los
términos salen de `mission` y `domain`, que son campos que un humano escribió al
crearla y que ella no puede modificar. Aprender aquí significa *darse cuenta de
lo que ya se declaró que era*, no decidir qué quiere ser.

Todo término aprendido queda con procedencia (`source: charter`), de modo que
una auditoría puede distinguirlo de uno declarado por una persona, y revertirlo.

Límites explícitos
------------------
- Solo de `mission` y `domain`. Nunca del texto del usuario, de sus respuestas
  ni de runs: eso sí permitiría ampliarse hacia donde hay tráfico.
- Se descartan palabras vacías y términos demasiado cortos o demasiado genéricos:
  un trigger que coincide con todo activa siempre, y una activación que ocurre
  siempre no es evidencia de nada.
- Tope por neurona. Sin tope, una misión larga se traduce en una red de arrastre.
- Nunca sobrescribe triggers declarados por un humano: solo añade.
- `identity_core` queda fuera de alcance, como siempre.
"""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from pathlib import Path
from typing import Any

#: Máximo de términos aprendidos por neurona. Una misión larga no debe
#: convertirse en una red de arrastre que capture cualquier conversación.
MAX_LEARNED_TRIGGERS = 8

#: Longitud mínima. Por debajo de esto los términos coinciden con demasiadas
#: palabras («los», «con», «api») y la activación deja de significar algo.
MIN_TRIGGER_LENGTH = 5

#: Palabras que aparecen en casi cualquier misión y no distinguen nada.
_STOPWORDS = frozenset(
    ["para", "por", "con", "sin", "sobre", "entre", "desde", "hasta", "como", "cuando", "donde", "the", "and", "for", "with", "without", "from", "into", "that", "this", "then", "than", "neurona", "neuron", "sistema", "system", "triade", "proponer", "proponer", "analizar", "describir", "mediante", "permitidos", "limites", "evidencia", "evidence", "generar", "usar", "hacer", "tener", "puede", "debe"]
)

#: Verbos de intención y muletillas. No son temas: dicen *que* alguien pide algo,
#: no *de qué* trata. `quiero` salió como trigger de una neurona cuya misión era
#: "Quiero informacion sobre la Banda Epica", y habría capturado media
#: conversación —incluida «quiero aprender a dibujar», que es de otra neurona—.
_GENERIC_INTENT = frozenset(
    ["quiero", "quisiera", "queria", "necesito", "necesitaria", "podrias", "puedes", "ayuda", "ayudame", "informacion", "favor", "gracias", "saber", "dime", "cuentame", "explicame"]
)

#: Términos de ciclo de vida que ya usa el runtime: no son palabras de usuario.
_LIFECYCLE = frozenset(
    {"every_session", "relevant_context", "candidate_state_review", "always"}
)


def _normalise(text: str) -> str:
    """Sin tildes y en minúsculas: 'imágenes' y 'imagenes' son la misma palabra."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def derive_triggers(neuron: dict[str, Any]) -> list[str]:
    """Términos de activación que la neurona puede justificar con su carta.

    Devuelve solo lo que aporta la propia declaración de la neurona. Si su misión
    no dice nada específico, devuelve poco o nada — y eso es correcto: una
    neurona que no sabe declarar para qué sirve no debería atraer tráfico.
    """
    charter = " ".join(
        [
            str(neuron.get("mission") or ""),
            str(neuron.get("domain") or "").replace("_", " "),
        ]
    )
    words = re.findall(r"[a-zA-ZáéíóúñüÁÉÍÓÚÑÜ]{3,}", charter)

    seen: list[str] = []
    for raw in words:
        term = _normalise(raw)
        if len(term) < MIN_TRIGGER_LENGTH:
            continue
        if term in _STOPWORDS or term in _LIFECYCLE or term in _GENERIC_INTENT:
            continue
        # Se guarda la raíz: «imágenes» debe casar con «imagen» en la pregunta.
        stem = term[:-2] if term.endswith("es") and len(term) > 6 else term
        stem = stem[:-1] if stem.endswith("s") and len(stem) > 5 else stem
        if stem not in seen:
            seen.append(stem)
        if len(seen) >= MAX_LEARNED_TRIGGERS:
            break
    return seen


class NeuronTriggerLearner:
    """Persiste los términos que cada neurona deduce de su propia carta."""

    def __init__(self, db_path: str | Path = "triade/memory/triade.db") -> None:
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def plan(self, *, only_empty: bool = True) -> list[dict[str, Any]]:
        """Qué aprendería cada neurona, **sin escribir nada**.

        Existe separado de `apply()` a propósito: un cambio que altera qué
        neuronas reciben tráfico debe poder mirarse antes de aplicarse.
        """
        proposals: list[dict[str, Any]] = []
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, name, domain, mission, triggers, status
                FROM neurons
                WHERE status IN ('candidate','experimental','active_assistant',
                                 'trusted_worker','stable')"""
            ).fetchall()
        for row in rows:
            neuron = dict(row)
            existing = _decode_triggers(neuron.get("triggers"))
            declared = [t for t in existing if t not in _LIFECYCLE]
            if only_empty and declared:
                # Ya hay términos útiles declarados: no se toca. Aprender no
                # puede significar pisar lo que decidió una persona.
                continue
            learned = [t for t in derive_triggers(neuron) if t not in existing]
            if not learned:
                continue
            proposals.append(
                {
                    "neuron_id": neuron["id"],
                    "name": neuron["name"],
                    "domain": neuron["domain"],
                    "existing_triggers": existing,
                    "learned_triggers": learned,
                    "source": "charter",
                    "justification": str(neuron.get("mission") or "")[:200],
                }
            )
        return proposals

    def apply(self, proposals: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Escribe los términos aprendidos, conservando los ya declarados."""
        pending = self.plan() if proposals is None else proposals
        updated = 0
        with self._connect() as conn:
            for proposal in pending:
                merged = list(proposal["existing_triggers"])
                for term in proposal["learned_triggers"]:
                    if term not in merged:
                        merged.append(term)
                conn.execute(
                    "UPDATE neurons SET triggers = ?, updated_at = datetime('now') "
                    "WHERE id = ?",
                    (json.dumps(merged, ensure_ascii=False), proposal["neuron_id"]),
                )
                updated += 1
            conn.commit()
        return {
            "updated": updated,
            "source": "charter",
            "proposals": pending,
            # Se dice explícitamente: esto no es una neurona decidiendo qué
            # quiere ser, es una neurona leyendo lo que ya se declaró que era.
            "self_granted_scope": False,
        }


def _decode_triggers(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(x) for x in raw]
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    return []
