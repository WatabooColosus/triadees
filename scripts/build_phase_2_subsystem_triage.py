"""Construye el triaje individual y reproducible de los 72 subsistemas.

No reclasifica la deuda de origen. Enriquece cada hallazgo
``incomplete_subsystem`` con evidencia estática, runtime y una decisión explícita.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypedDict

from triade.observability.code_graph import build_module_index, reachable_modules

Decision = Literal[
    "activate_now",
    "complete_later",
    "merge_with_existing",
    "experimental_keep",
    "legacy_archive",
    "remove_from_productive_graph",
]
DECISION_VALUES: tuple[Decision, ...] = (
    "activate_now",
    "complete_later",
    "merge_with_existing",
    "experimental_keep",
    "legacy_archive",
    "remove_from_productive_graph",
)


class Review(TypedDict):
    group: str
    mission: str
    owner: str
    decision: Decision
    reason: str
    required_work: str
    priority: str
    business_value: str
    architectural_value: str


def _review(
    group: str,
    mission: str,
    owner: str,
    decision: Decision,
    reason: str,
    required_work: str,
    priority: str = "P2",
    business_value: str = "medium",
    architectural_value: str = "medium",
) -> Review:
    return {
        "group": group,
        "mission": mission,
        "owner": owner,
        "decision": decision,
        "reason": reason,
        "required_work": required_work,
        "priority": priority,
        "business_value": business_value,
        "architectural_value": architectural_value,
    }


# Juicio explícito por subsistema único. Las observaciones duplicadas conservan su
# ID y comparten decisión, pero explican la categoría que las detectó.
REVIEWS: dict[str, Review] = {
    "unhealthy": _review(
        "B",
        "Supervisar workers no saludables",
        "workers",
        "remove_from_productive_graph",
        "El estado es inalcanzable y no tiene productor; presentarlo como vivo falsea la supervisión.",
        "Retirar el estado del grafo productivo o sustituirlo por el contrato vivo de salud con prueba E2E.",
        "P1",
        "medium",
        "high",
    ),
    "benchmark_tasks": _review(
        "A",
        "Persistir tareas de benchmark",
        "evaluation",
        "merge_with_existing",
        "Está vacío y desconectado mientras autonomous_tasks ya ofrece cola y ciclo de vida.",
        "Definir migración no destructiva o adaptador hacia autonomous_tasks y verificar equivalencia.",
    ),
    "benchmark_results": _review(
        "A",
        "Persistir resultados de benchmark",
        "evaluation",
        "legacy_archive",
        "Tabla viva sin productor ni consumidor; los artefactos versionados son hoy la fuente demostrada.",
        "Documentar procedencia histórica y mantenerla fuera del grafo productivo hasta existir consumidor real.",
        "P3",
        "low",
        "low",
    ),
    "federated_merge_nodes": _review(
        "D",
        "Representar nodos durante una fusión federada",
        "federation",
        "merge_with_existing",
        "Duplica federated_nodes, que sí contiene actividad runtime.",
        "Definir compatibilidad y migración hacia federated_nodes sin crear filas artificiales.",
    ),
    "federated_merge_log": _review(
        "D",
        "Auditar fusiones federadas",
        "federation",
        "merge_with_existing",
        "No tiene productor ni consumidor y se solapa con federated_exchange_log.",
        "Unificar el contrato de auditoría con federated_exchange_log y añadir lectura operacional.",
    ),
    "neuron_education_applications": _review(
        "A",
        "Aplicar educación gobernada a neuronas",
        "learning",
        "complete_later",
        "Tiene lectores y escritores reales pero cero uso runtime; no hay prueba de aplicación end-to-end.",
        "Ejecutar solicitud, aplicación, efecto medido, auditoría y rollback sobre una neurona de prueba.",
        "P1",
        "high",
        "high",
    ),
    "runtime_queue_compatibility_events": _review(
        "B",
        "Auditar compatibilidad entre colas runtime",
        "runtime",
        "merge_with_existing",
        "Escribe una tabla vacía que se solapa con runtime_queue_compatibility, ya activa.",
        "Consolidar evento y estado en un contrato único con migración y lector observable.",
    ),
    "auto_identity": _review(
        "C",
        "Mantener identidad automática gobernada",
        "identity",
        "complete_later",
        "Hay código lector/escritor pero cero evidencia runtime; identidad es frontera protegida.",
        "Revisión humana especializada y prueba aislada sin modificar identity_core ni producción.",
        "P3",
        "high",
        "high",
    ),
    "capability_history": _review(
        "A",
        "Registrar cambios del catálogo de capacidades",
        "capabilities",
        "complete_later",
        "La ruta existe pero nunca produjo filas observadas.",
        "Probar registro, consulta, trazabilidad y rollback durante un cambio real de capacidad.",
        "P2",
        "medium",
        "high",
    ),
    "capability_registry": _review(
        "A",
        "Resolver capacidades disponibles",
        "capabilities",
        "complete_later",
        "Lectores y escritor existen, pero el registro vivo permanece vacío y no está validado E2E.",
        "Conectar únicamente a un resolver consumidor real y cubrir alta, resolución, rechazo y auditoría.",
        "P1",
        "high",
        "high",
    ),
    "federated_exchange_log": _review(
        "D",
        "Auditar intercambios federados",
        "federation",
        "complete_later",
        "Tiene circuito estructural pero no actividad runtime observada.",
        "Ejecutar intercambio permitido y rechazado, comprobar consumidor, seguridad y evidencia.",
        "P2",
        "medium",
        "high",
    ),
    "goal_dependencies": _review(
        "B",
        "Modelar dependencias entre goals",
        "goals",
        "complete_later",
        "Escritor y lector no han producido actividad; depende de cerrar Goals E2E.",
        "Validar dependencia, bloqueo, desbloqueo, ciclo y cierre durante Fase 3.",
        "P1",
        "high",
        "high",
    ),
    "goals": _review(
        "B",
        "Persistir el ciclo de vida de goals",
        "goals",
        "complete_later",
        "El circuito existe pero tiene cero filas y carece de validación end-to-end.",
        "Completar los once casos obligatorios de Goals con deduplicación y estados terminales.",
        "P1",
        "high",
        "high",
    ),
    "governed_peft_active_slot": _review(
        "A",
        "Seleccionar adaptador PEFT activo bajo gobernanza",
        "models",
        "complete_later",
        "El slot no registra actividad y no existe promoción demostrada en runtime productivo.",
        "Probar selección, canary, aprobación, rollback y serving antes de activarlo.",
        "P2",
        "medium",
        "high",
    ),
    "kg_contradictions": _review(
        "A",
        "Registrar contradicciones del grafo de conocimiento",
        "knowledge",
        "experimental_keep",
        "La arquitectura está implementada pero no tiene hechos runtime ni consumidor productivo demostrado.",
        "Conservar como experimental y crear benchmark de contradicción con consumidor antes de promoción.",
        "P3",
        "medium",
        "medium",
    ),
    "kg_edges": _review(
        "A",
        "Representar relaciones del grafo de conocimiento",
        "knowledge",
        "experimental_keep",
        "La tabla está vacía y el grafo semántico no está demostrado productivamente.",
        "Conservar aislado; demostrar productor, consulta y utilidad frente a baseline.",
        "P3",
        "medium",
        "medium",
    ),
    "kg_nodes": _review(
        "A",
        "Representar entidades del grafo de conocimiento",
        "knowledge",
        "experimental_keep",
        "Tiene código estructural sin datos ni uso productivo observado.",
        "Conservar aislado; validar ingesta, recuperación y no regresión antes de promoción.",
        "P3",
        "medium",
        "medium",
    ),
    "neuron_certifications": _review(
        "A",
        "Certificar neuronas antes de promoción",
        "verification",
        "complete_later",
        "Sólo existe lector no alcanzable y ningún escritor; no es un corte productivo.",
        "Definir productor gobernado, consumidor de promoción y prueba E2E de rechazo/aprobación.",
        "P2",
        "high",
        "high",
    ),
    "orchestrator_locks": _review(
        "B",
        "Evitar ejecuciones concurrentes incompatibles",
        "runtime",
        "complete_later",
        "Hay lectores/escritores pero no actividad observada ni prueba de exclusión global.",
        "Probar adquisición, fencing, expiración, recuperación e idempotencia.",
        "P1",
        "high",
        "high",
    ),
    "regression_quarantine": _review(
        "A",
        "Aislar candidatos con regresión",
        "regression",
        "complete_later",
        "El gate existe, pero la cuarentena persistida no se ha ejercitado en runtime.",
        "Ejecutar regresión crítica, cuarentena, recuperación y auditoría sin promoción.",
        "P1",
        "high",
        "high",
    ),
    "relational_modulation_events": _review(
        "E",
        "Registrar modulación relacional experimental",
        "research",
        "experimental_keep",
        "Código y tablas existen sin actividad productiva observada; no hay utilidad demostrada.",
        "Mantener fuera del grafo productivo y exigir benchmark causal antes de cualquier activación.",
        "P3",
        "low",
        "medium",
    ),
    "relational_modulation_states": _review(
        "E",
        "Persistir estado de modulación relacional",
        "research",
        "experimental_keep",
        "Subsistema filosófico sin consumidor productivo ni filas runtime.",
        "Conservar como experimental con etiquetado explícito y pruebas aisladas.",
        "P3",
        "low",
        "medium",
    ),
    "sandbox_executions": _review(
        "C",
        "Auditar ejecuciones aisladas",
        "sandbox",
        "complete_later",
        "El almacén existe pero no contiene ejecuciones; el sandbox fuerte es trabajo de Fase 6.",
        "Validar aislamiento, límites, violaciones, diff y rollback sin tocar el repositorio real.",
        "P1",
        "high",
        "high",
    ),
    "semantic_governance_events": _review(
        "A",
        "Auditar decisiones sobre memoria semántica",
        "memory",
        "complete_later",
        "Lectores y escritores existen sin eventos runtime observados.",
        "Ejecutar promoción y rechazo medidos, con trazabilidad y rollback.",
        "P1",
        "high",
        "high",
    ),
    "semantic_memory": _review(
        "A",
        "Recuperar conocimiento semántico consolidado",
        "memory",
        "complete_later",
        "Diez lectores y tres escritores no han producido filas en la base observada; no equivale a aprendizaje.",
        "Demostrar ingesta, recuperación causal, mejora y no regresión mediante consumidor productivo.",
        "P1",
        "high",
        "high",
    ),
    "stable_capability_state": _review(
        "A",
        "Mantener capacidades consolidadas estables",
        "capabilities",
        "complete_later",
        "La estructura existe sin estado runtime ni reutilización productiva demostrada.",
        "Probar promoción, lectura posterior, degradación y rollback gobernado.",
        "P1",
        "high",
        "high",
    ),
    "sin TRIADE_BACKUP_KEY ni TRIADE_BACKUP_KEY_FILE: no se crea ninguna copia y no se abre ninguna existente": _review(
        "D",
        "Crear y restaurar backups cifrados",
        "operations",
        "complete_later",
        "La ausencia de clave bloquea correctamente; inventar o almacenar secretos está prohibido.",
        "Proveer clave por operación autorizada y demostrar backup, integridad y restore sin exponerla.",
        "P1",
        "high",
        "high",
    ),
    "triade/capabilities/matrix.py": _review(
        "A",
        "Calcular matriz de capacidades",
        "capabilities",
        "remove_from_productive_graph",
        "Retirada el 2026-08-08. El `merge_with_existing` anterior daba por "
        "supuesto que quedaba lógica no duplicada que extraer; medida sobre el "
        "registro ya lleno, no queda ninguna: los ciclos y las críticas sin "
        "rollback los rechaza `register()` al escribir, `quarantined` no lo "
        "asigna nadie, el baseline lo juzga y lo aplica `MandatoryRollbackEnforcer` "
        "y los recuentos los publica `CapabilityObservability`.",
        "Hecho. Copia en artifacts/dead_code_backup/, veredicto en "
        "docs/debt/CAPABILITY_MATRIX_VERDICT.md.",
        "P2",
        "medium",
        "medium",
    ),
    "triade/core/hierarchical_pulse.py": _review(
        "E",
        "Modelar pulsos jerárquicos experimentales",
        "research",
        "experimental_keep",
        "No tiene importador ni entrypoint vivo y no existe consumidor demostrado.",
        "Etiquetar experimental, conservar pruebas aisladas y prohibir presentación como runtime vivo.",
        "P3",
        "low",
        "low",
    ),
    "triade/core/plan_step.py": _review(
        "B",
        "Representar pasos de plan",
        "goals",
        "merge_with_existing",
        "Módulo huérfano que se solapa con contratos de planning ya usados.",
        "Comparar contratos, extraer campos únicos y retirar el duplicado del grafo productivo.",
        "P2",
        "medium",
        "medium",
    ),
    "meta_model_candidates": _review(
        "E",
        "Persistir candidatos de meta-modelo",
        "research",
        "experimental_keep",
        "Tabla sin productor ni consumidor y meta-orquestación no demostrada.",
        "Conservar como experimental o archivar junto con su migración tras confirmar ausencia de necesidad.",
        "P3",
        "low",
        "low",
    ),
    "meta_model_decisions": _review(
        "E",
        "Persistir decisiones de meta-modelo",
        "research",
        "experimental_keep",
        "No hay circuito runtime ni consumidor real.",
        "Mantener fuera del producto hasta benchmark, policy y rollback demostrados.",
        "P3",
        "low",
        "low",
    ),
    "meta_model_evaluations": _review(
        "E",
        "Evaluar candidatos de meta-modelo",
        "research",
        "experimental_keep",
        "Tabla desconectada sin mediciones runtime.",
        "Exigir Measurement Core y consumidor antes de activación.",
        "P3",
        "low",
        "medium",
    ),
    "metabolic_config": _review(
        "E",
        "Configurar metabolismo experimental",
        "research",
        "experimental_keep",
        "Tabla desconectada y sin consumidor; la metáfora no constituye capacidad.",
        "Mantener experimental y documentar que no está activa.",
        "P3",
        "low",
        "low",
    ),
    "user_sessions": _review(
        "C",
        "Persistir sesiones autenticadas",
        "security",
        "merge_with_existing",
        "Tabla desconectada que puede solaparse con el mecanismo actual de autenticación.",
        "Auditar el contrato de sesión vigente y migrar sólo si preserva fronteras y revocación.",
        "P2",
        "high",
        "high",
    ),
    "engineering_evolution_events": _review(
        "D",
        "Auditar eventos de evolución de ingeniería",
        "observability",
        "complete_later",
        "Tiene productor y filas, pero ningún lector: actividad almacenada sin utilidad operativa.",
        "Añadir consumidor de reporte real o retirar la escritura del grafo productivo.",
        "P2",
        "medium",
        "medium",
    ),
    "evidence_remediation_audit": _review(
        "D",
        "Auditar remediaciones de evidencia",
        "observability",
        "complete_later",
        "Acumula 479 filas sin lector; la auditoría no es verificable desde una interfaz viva.",
        "Crear consulta gobernada y política de retención, con prueba de lectura y trazabilidad.",
        "P1",
        "high",
        "high",
    ),
    "governed_research_runs": _review(
        "D",
        "Consultar investigaciones gobernadas",
        "research",
        "complete_later",
        "Hay 86 runs escritos y ningún consumidor, por lo que no informan decisiones posteriores.",
        "Añadir recuperación y uso auditado o detener la producción de filas.",
        "P2",
        "medium",
        "high",
    ),
    "hardware_senses": _review(
        "D",
        "Observar recursos de hardware",
        "operations",
        "complete_later",
        "Hay 293 muestras y ningún consumidor; medir sin actuar no demuestra salud.",
        "Conectar a ready/deep o reporte con umbrales y prueba de decisión, no al heartbeat ligero.",
        "P1",
        "high",
        "high",
    ),
    "neuron_certification_transitions": _review(
        "A",
        "Auditar transiciones de certificación",
        "verification",
        "complete_later",
        "Existen 13 transiciones sin lector, así que no gobiernan promoción ni revisión.",
        "Añadir consumidor de auditoría y probar transición, consulta y rollback.",
        "P2",
        "high",
        "high",
    ),
    "bodega_global_review": _review(
        "B",
        "Revisar globalmente la bodega",
        "workers",
        "complete_later",
        "Task type declarado pero nunca ejecutado; no hay evidencia de efecto ni terminación.",
        "Completar contrato de tarea y ejecutar cola, handler, evidencia y terminal en Fase 4.",
        "P2",
        "medium",
        "medium",
    ),
    "federation_inbox_review": _review(
        "B",
        "Revisar inbox federado",
        "federation",
        "complete_later",
        "Task type sin ejecución observada; la entrada federada añade riesgo de seguridad.",
        "Probar mensaje permitido/rechazado, handler, idempotencia y auditoría.",
        "P2",
        "medium",
        "high",
    ),
    "goal_install": _review(
        "B",
        "Instalar una capacidad solicitada por un goal",
        "goals",
        "complete_later",
        "Nunca ejecutada y puede instalar dependencias, operación que requiere aprobación explícita.",
        "Definir policy, aprobación, sandbox, rollback y estado terminal antes de ejecutar.",
        "P1",
        "high",
        "high",
    ),
    "goal_lora_train": _review(
        "B",
        "Entrenar LoRA desde un goal gobernado",
        "goals",
        "complete_later",
        "Nunca ejecutada; coste GPU y promoción requieren contratos de workers y modelos.",
        "Definir recursos, policy, handler, evidencia, canary y rollback antes de habilitar.",
        "P2",
        "medium",
        "high",
    ),
    "self_improvement_canary_observation": _review(
        "E",
        "Observar canary de auto-mejora",
        "self_improvement",
        "experimental_keep",
        "Task type experimental nunca ejecutado productivamente.",
        "Mantener aislado hasta demostrar canary, medición causal y rollback.",
        "P3",
        "medium",
        "high",
    ),
    "self_improvement_evaluation": _review(
        "E",
        "Evaluar una propuesta de auto-mejora",
        "self_improvement",
        "experimental_keep",
        "No hay ejecución runtime; código existente no demuestra reparación ni mejora.",
        "Conservar experimental y exigir baseline, tratamiento, regresión y decisión humana.",
        "P3",
        "medium",
        "high",
    ),
    "stable_consolidation_review": _review(
        "A",
        "Revisar consolidación de conocimiento estable",
        "learning",
        "complete_later",
        "Task type nunca ejecutado pese a que consolidación requiere consumidor y auditoría.",
        "Ejecutar revisión aprobada/rechazada con evidencia y efecto posterior medido.",
        "P1",
        "high",
        "high",
    ),
    "write_governed_text_artifact": _review(
        "C",
        "Escribir artefactos de texto gobernados",
        "sandbox",
        "complete_later",
        "Operación de filesystem nunca ejecutada; requiere rutas permitidas e idempotencia.",
        "Cubrir path traversal, symlink, overwrite, manifest, diff y rollback en sandbox.",
        "P1",
        "medium",
        "high",
    ),
    "plan: 51 filas, ninguna en 24 h": _review(
        "B",
        "Mantener activo el tramo plan del circuito vital",
        "goals",
        "complete_later",
        "Hay historia, pero ninguna actividad reciente; no demuestra un circuito actual vivo.",
        "Ejecutar input→goal→plan→task→result→close y observar actividad reciente en Fase 3.",
        "P1",
        "high",
        "high",
    ),
}


AUDIT_ONLY_FILES = {
    "scripts/build_phase_2_subsystem_triage.py",
    "scripts/triage_debt.py",
    "triade/observability/alias_debt.py",
    "triade/observability/introspection.py",
}


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for base in ("triade", "apps", "scripts"):
        for path in (root / base).rglob("*.py"):
            relative = path.relative_to(root).as_posix()
            if "__pycache__" not in path.parts and relative not in AUDIT_ONLY_FILES:
                files.append(path)
    return sorted(files)


def _references(
    root: Path,
    name: str,
    source_file: str,
    category: str,
    source_texts: dict[str, str],
) -> tuple[list[str], list[str], list[str]]:
    if name.endswith(".py") and (root / name).exists():
        return [name], [], []
    if category in {"alias_debt_dead_status_value", "alias_debt_suspected_dead_status"}:
        return ([source_file], [], [source_file]) if source_file else ([], [], [])
    token = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])")
    write = re.compile(
        rf"(?:INSERT\s+INTO|UPDATE|CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?)\s+['\"`]?{re.escape(name)}\b",
        re.IGNORECASE,
    )
    read = re.compile(
        rf"(?:FROM|JOIN)\s+['\"`]?{re.escape(name)}\b",
        re.IGNORECASE,
    )
    files: list[str] = []
    producers: list[str] = []
    consumers: list[str] = []
    for relative, text in source_texts.items():
        if not token.search(text):
            continue
        files.append(relative)
        if write.search(text) or (
            category == "task_types_never_executed"
            and re.search(
                rf"{re.escape(name)}[^\n]{{0,160}}(?:enqueue|submit|create_task|task_type)",
                text,
                re.IGNORECASE,
            )
        ):
            producers.append(relative)
        if read.search(text) or (
            category == "task_types_never_executed"
            and re.search(
                rf"{re.escape(name)}[^\n]{{0,160}}(?:handler|operation|dispatch)",
                text,
                re.IGNORECASE,
            )
        ):
            consumers.append(relative)
    if source_file and source_file.endswith(".py") and source_file not in files:
        files.append(source_file)
    return sorted(files), sorted(producers), sorted(consumers)


def _tests(name: str, test_texts: dict[str, str]) -> list[str]:
    needle = name.removesuffix(".py").split("/")[-1]
    found = [relative for relative, text in test_texts.items() if needle in text]
    return found[:6]


def _last_activity(root: Path, files: list[str]) -> str:
    if not files:
        return "not_observed"
    result = subprocess.run(
        ["git", "log", "-1", "--format=%cI", "--", *files],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() or "not_observed"


def _security_risk(name: str, review: Review) -> str:
    joined = f"{name} {review['owner']}"
    if any(
        word in joined
        for word in ("identity", "sandbox", "backup", "session", "install")
    ):
        return "high"
    if any(
        word in joined
        for word in ("federat", "lock", "peft", "lora", "self_improvement")
    ):
        return "medium"
    return "low"


def build(root: Path, source_path: Path) -> dict[str, Any]:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    findings = [
        item
        for item in source["findings"]
        if item["classification"] == "incomplete_subsystem"
    ]
    names = [str(item["table_or_status"]) for item in findings]
    missing_reviews = sorted(set(names) - REVIEWS.keys())
    extra_reviews = sorted(REVIEWS.keys() - set(names))
    if missing_reviews or extra_reviews:
        raise ValueError(
            f"review mismatch: missing={missing_reviews}, extra={extra_reviews}"
        )

    duplicates: dict[str, list[str]] = {}
    for item in findings:
        duplicates.setdefault(str(item["table_or_status"]), []).append(str(item["id"]))

    reachable = reachable_modules(root, build_module_index(root))
    table_graph_path = root / "artifacts/internal_graphs/table_graph.json"
    table_graph = json.loads(table_graph_path.read_text(encoding="utf-8"))
    table_names = {node["label"] for node in table_graph.get("nodes", [])}
    source_texts = {
        path.relative_to(root).as_posix(): path.read_text(
            encoding="utf-8", errors="ignore"
        )
        for path in _source_files(root)
    }
    test_texts = {
        path.relative_to(root).as_posix(): path.read_text(
            encoding="utf-8", errors="ignore"
        )
        for path in sorted((root / "tests").rglob("test_*.py"))
    }

    reviewed: list[dict[str, Any]] = []
    for item in findings:
        name = str(item["table_or_status"])
        review = REVIEWS[name]
        files, producers, consumers = _references(
            root,
            name,
            str(item["source_file"]),
            str(item["category"]),
            source_texts,
        )
        live_files = sorted(set(files) & reachable)
        existing_tests = _tests(name, test_texts)
        duplicate_ids = [
            item_id for item_id in duplicates[name] if item_id != item["id"]
        ]
        tests_needed = existing_tests or [
            f"proposed:test_{re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')}_end_to_end"
        ]
        reviewed.append(
            {
                "id": item["id"],
                "name": name,
                "group": review["group"],
                "owner": review["owner"],
                "files": files,
                "tables": [name] if name in table_names else [],
                "mission": review["mission"],
                "producer": producers or ["not_demonstrated"],
                "consumer": consumers or ["not_demonstrated"],
                "entrypoint": live_files[0] if live_files else "none",
                "reachable": bool(live_files),
                "runtime_rows": item["runtime_rows"],
                "last_activity": _last_activity(root, files),
                "dependencies": sorted(
                    {path.split("/")[1] if "/" in path else path for path in files}
                ),
                "security_risk": _security_risk(name, review),
                "business_value": review["business_value"],
                "architectural_value": review["architectural_value"],
                "duplication": {
                    "other_finding_ids": duplicate_ids,
                    "detector_category": item["category"],
                    "impact": item["impact"],
                },
                "decision": review["decision"],
                "reason": review["reason"],
                "required_work": review["required_work"],
                "tests_needed": tests_needed,
                "priority": review["priority"],
                "source_evidence": item["evidence"],
            }
        )

    reviewed.sort(key=lambda item: (item["group"], int(str(item["id"])[1:])))
    counts: dict[str, int] = {decision: 0 for decision in DECISION_VALUES}
    for item in reviewed:
        counts[item["decision"]] = counts.get(item["decision"], 0) + 1
    return {
        "schema_version": "1.0.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "base_sha": subprocess.run(
            ["git", "merge-base", "HEAD", "main"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "source_artifact": source_path.relative_to(root).as_posix(),
        "source_incomplete_subsystem_count": len(findings),
        "reviewed_count": len(reviewed),
        "unique_subsystem_count": len(set(names)),
        "decision_counts": counts,
        "activation_gate": {
            "activate_now_count": counts.get("activate_now", 0),
            "rule": "need + producer + consumer + live entrypoint + E2E test + observability",
        },
        "reviews": reviewed,
    }


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_report(result: dict[str, Any], branch: str) -> str:
    counts = result["decision_counts"]
    duplicate_names = len(
        {
            item["name"]
            for item in result["reviews"]
            if item["duplication"]["other_finding_ids"]
        }
    )
    lines = [
        "# Fase 2 — Triaje individual de subsistemas",
        "",
        "## SHA base, rama y objetivo",
        "",
        f"- SHA base: `{result['base_sha']}`.",
        f"- Rama: `{branch}`.",
        "- Objetivo: revisar individualmente las 72 observaciones `incomplete_subsystem` sin reducir ni ocultar deuda.",
        "",
        "## Estado inicial y método",
        "",
        f"La fuente canónica es `{result['source_artifact']}`: 72 observaciones y 49 subsistemas únicos. {duplicate_names} subsistemas aparecen en dos o tres categorías; se conservan todos los IDs y cada duplicación referencia los otros hallazgos.",
        "",
        "El generador inspecciona código, grafo de tablas, alcanzabilidad desde entrypoints, filas runtime, pruebas y última actividad Git. La automatización valida evidencia y completitud; no inventa activación.",
        "",
        "## Diferencia de estados",
        "",
        "- **Código existente:** ficheros o tablas identificados en repositorio/grafo.",
        "- **Código alcanzable:** alguna referencia deriva de un entrypoint vivo.",
        "- **Código probado:** una prueba nombra el subsistema; no implica E2E.",
        "- **Código ejecutado:** existe ejecución observada, no sólo declaración.",
        "- **Runtime observado:** filas y actividad vienen del artefacto vivo de origen.",
        "- **Capacidad demostrada:** exige productor, consumidor, entrypoint, E2E y observabilidad; ninguno de estos 72 cumple todo el gate.",
        "",
        "## Hallazgos y causas",
        "",
        "- La deuda mezcla tablas vacías, task types nunca ejecutados, telemetría sin lector, módulos huérfanos y experimentos.",
        "- Una tabla con filas no demuestra utilidad si nadie las consume; una tabla vacía no se completa creando filas artificiales.",
        "- Los módulos experimentales permanecen etiquetados como tales.",
        "- No se modifica identidad, secretos, permisos ni fronteras de seguridad.",
        "",
        "## Decisiones",
        "",
        "| Decisión | Cantidad |",
        "|---|---:|",
    ]
    for decision in DECISION_VALUES:
        lines.append(f"| `{decision}` | {counts.get(decision, 0)} |")
    lines.extend(
        [
            "",
            "No hay `activate_now`: ante ausencia de E2E u observabilidad la decisión obligatoria es no demostrado.",
            "",
            "## Revisión 72/72",
            "",
            "| ID | Grupo | Subsistema | Owner | Alcanzable | Filas | Decisión | Prioridad | Razón |",
            "|---|---|---|---|---:|---:|---|---|---|",
        ]
    )
    for item in result["reviews"]:
        values = (
            item["id"],
            item["group"],
            item["name"],
            item["owner"],
            "sí" if item["reachable"] else "no",
            item["runtime_rows"],
            f"`{item['decision']}`",
            item["priority"],
            item["reason"],
        )
        lines.append("| " + " | ".join(_cell(value) for value in values) + " |")
    lines.extend(
        [
            "",
            "## Cambios, archivos y migraciones",
            "",
            "- `scripts/build_phase_2_subsystem_triage.py`: política explícita, evidencia y generación reproducible.",
            "- `artifacts/evolution/subsystem_triage.json`: contrato completo 72/72.",
            "- `tests/test_phase_2_subsystem_triage.py`: gates arquitectónicos del inventario.",
            "- Este informe: vista humana completa.",
            "- Migraciones: ninguna. No se crean tablas ni filas para silenciar alertas.",
            "",
            "## Pruebas, benchmark y regresiones",
            "",
            "La suite específica valida cardinalidad, IDs, campos, owners, decisiones, duplicaciones, gate de activación y etiquetado experimental. Esta fase es de auditoría: la comparación aplicable exige conservar 72 → 72 observaciones.",
            "",
            "Antes del PR se ejecutan compileall, Ruff, formato, mypy, suite global y suite específica. Sólo entonces puede declararse ausencia de regresiones.",
            "",
            "## Criterio de cierre",
            "",
            "- 72/72 observaciones revisadas y con exactamente una decisión.",
            "- 72/72 con owner, razón, trabajo requerido y pruebas necesarias.",
            "- 0 activaciones sin productor, consumidor, entrypoint, E2E y observabilidad.",
            "- 0 experimentales presentados como vivos.",
            "- 0 contadores reducidos; las 72 observaciones siguen trazadas.",
            "",
            "## Riesgos, rollback, deuda restante y recomendación",
            "",
            "El análisis estático identifica referencias pero no sustituye ejecución. `reachable=true` no significa usado ni útil. `complete_later` es backlog, no capacidad prometida.",
            "",
            "Rollback: revertir los commits de esta fase; no hay migración ni mutación runtime. La fuente histórica permanece intacta.",
            "",
            "Deuda restante: ejecutar cada trabajo en su fase y demostrar E2E antes de promover. La recomendación de merge se decide sólo tras gates terminales; nunca merge automático.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--source", type=Path, default=Path("artifacts/debt/debt-triage-20260803.json")
    )
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/evolution/subsystem_triage.json")
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("docs/evolution/PHASE_2_SUBSYSTEM_TRIAGE.md"),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    source = args.source if args.source.is_absolute() else root / args.source
    output = args.output if args.output.is_absolute() else root / args.output
    report = args.report if args.report.is_absolute() else root / args.report
    result = build(root, source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result, branch), encoding="utf-8")
    print(
        json.dumps(
            {
                "reviewed": result["reviewed_count"],
                "decisions": result["decision_counts"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
