"""Selección de objetivos y material pertinente sin convertir candidatos en verdad."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

from triade.core.guarded_web import TRUSTED_RESEARCH_HOSTS


def admission_curriculum(
    db_path: str | Path, candidate_id: str, specification: dict[str, Any]
) -> dict[str, Any]:
    """Reserve transfer tasks before execution; never infer competence from IO.

    Only the existing independently attested procedural probe is supported.
    Other domains require a legitimate evaluator, rather than wildcard admission.
    """
    from triade.learning.knowledge_probe import build_transfer_probe

    threshold = specification["certification_requirements"].get("success_rate_min")
    if not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        raise ValueError("missing_predefined_certification_threshold")
    cases = {}
    for split, values in (("training", (3, 7)), ("held_out", (34, 41, 52, 63, 79))):
        cases[split] = []
        for value in values:
            probe = build_transfer_probe(db_path, candidate_id, value)
            if probe is None:
                raise ValueError("independent_transfer_evaluator_unavailable")
            cases[split].append(
                {
                    "case_id": f"{split}:{value}",
                    "input_value": value,
                    "question": probe.question,
                    "reference": probe.expected,
                }
            )
    manifest = {
        "version": 1,
        "candidate_id": candidate_id,
        "cases": cases,
        "success_rate_min": float(threshold),
        "negative_control_required": True,
        "regressions_max": 0,
        "resource_profile": specification["resource_profile"],
    }
    manifest["sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True).encode()
    ).hexdigest()
    return manifest


#: Qué se busca para cada dominio. **Fuente única**: la usa quien investiga
#: (`worker_loop._research_curriculum`) y quien selecciona material para la
#: lección (`NeuronEducationCycle`). Dos vocabularios distintos para la misma
#: neurona era el corte: la investigación traía documentación de gobernanza y el
#: currículo la buscaba por el nombre de la neurona —que en las nacidas de una
#: conversación es la frase que la creó, «Me llamo Santiago, soy el CEO de
#: Wataboo»—, así que lo investigado nunca resultaba relevante. Medido el
#: 2026-08-09: las seis neuronas medibles pasan de 1 a 2 fuentes independientes.
DOMAIN_QUERIES: dict[str, str] = {
    "live_pulse": "software observability service monitoring health checks heartbeat incident detection",
    "vision_image_understanding": "visión artificial procesamiento de imágenes OpenCV Pillow",
    "code_repair": "ingeniería de software depuración pruebas reproducibles",
    "code_repair_build_tests": (
        "ingeniería de software código depuración pruebas testing pytest unittest"
    ),
    "system_governance": "gobernanza de sistemas software auditoría trazabilidad",
}


def domain_query(domain: str) -> str:
    return DOMAIN_QUERIES.get(domain, domain.replace("_", " "))


def terms(text: str) -> set[str]:
    stop = {
        "para",
        "como",
        "que",
        "una",
        "con",
        "por",
        "del",
        "the",
        "and",
        "mission",
        "neurona",
    }
    return {
        word
        for word in re.findall(r"[a-záéíóúñ0-9]{3,}", text.lower().replace("_", " "))
        if word not in stop
    }


def source_domain(source_ref: str) -> str:
    return (
        urllib.parse.urlparse(source_ref).hostname or source_ref.split(":", 1)[0]
    ).lower()


def relevant_material(
    rows: list[dict[str, Any]], objective: str, domain: str, *, limit: int = 5
) -> list[dict[str, Any]]:
    wanted = terms(f"{objective} {domain}")
    ranked = []
    for row in rows:
        overlap = wanted & terms(
            f"{row.get('title', '')} {row.get('content', '')} {row.get('domain', '')}"
        )
        score = len(overlap) / max(1, len(wanted))
        host = source_domain(str(row.get("source_ref") or ""))
        governed_docs = host in TRUSTED_RESEARCH_HOSTS
        minimum = (
            0.05
            if governed_docs
            else 0.10
            if row.get("source_type") in {"web", "document"}
            else 0.15
        )
        if score >= minimum and row.get("source_ref"):
            ranked.append(({**row, "relevance": round(score, 3)}, score))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return [item[0] for item in ranked[:limit]]
