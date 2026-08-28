"""Rutas administrativas de backup, LoRA y serving canary."""

from __future__ import annotations

import os
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from apps.routes.api import require_key
from triade.db import sqlite3

router = APIRouter(prefix="/api/governance", tags=["governance"])


class CanaryRequest(BaseModel):
    adapter_path: str
    prompt: str = Field(min_length=1, max_length=4000)
    max_new_tokens: int = Field(default=64, ge=1, le=256)


class AdapterDecision(BaseModel):
    adapter_path: str
    approved_by: str = Field(min_length=1)


class GovernedAdapterDecision(BaseModel):
    version_id: str = Field(min_length=1)
    approved_by: str = Field(min_length=1)


class ImprovementTargetDecision(BaseModel):
    neuron_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    assigned_by: str = Field(min_length=1)


class LoraRequest(BaseModel):
    dataset_path: str
    approved_by: str = Field(min_length=1)
    base_model: str | None = None
    max_steps: int = Field(default=20, ge=1, le=100)
    ood_path: str | None = None
    forgetting_path: str | None = None
    maximum_gpu_minutes: float = Field(default=30.0, ge=1.0, le=120.0)


class EvolutionRequest(BaseModel):
    objective: str = Field(min_length=5, max_length=500)
    hypothesis: str = Field(min_length=5, max_length=2000)
    patch: str = Field(min_length=10, max_length=100_000)


class EvolutionApproval(BaseModel):
    approved_by: str = Field(min_length=1)


class ImprovementSignalRequest(BaseModel):
    capability_id: str = Field(min_length=1)
    metric_id: str = Field(min_length=1)
    observed_score: float
    target_score: float
    impact: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    estimated_cost: float = Field(default=1.0, ge=0.0)
    risk_level: str = "low"
    source_ref: str | None = None


class NeuronSpecificationRequest(BaseModel):
    """Lo que sólo puede decidir una persona; el resto sale de la neurona."""

    version: str = Field(min_length=1)
    component: str = Field(min_length=1)
    provides_capabilities: list[str] = Field(min_length=1)
    max_memory_mb: int = Field(gt=0, le=8192)
    max_runtime_seconds: int = Field(gt=0, le=3600)
    max_storage_mb: int = Field(gt=0, le=4096)
    approved_by: str = Field(min_length=1)
    requires_capabilities: list[str] = Field(default_factory=list)
    evaluation_suites: list[str] = Field(default_factory=list)
    rollback_policy: str | None = None
    critical: bool = False


class ImprovementProposalRequest(BaseModel):
    signal_id: str = Field(min_length=1)
    hypothesis: str = Field(min_length=5, max_length=2000)
    requested_capability: str = Field(min_length=1)
    max_candidates: int = Field(default=1, ge=1, le=5)
    # A qué neurona y versión apunta la mejora. Sin esto la propuesta se aprueba
    # y muere en el handler, que exige la terna completa para su clave de
    # idempotencia. Ver `ImprovementProposal.neuron_id`.
    neuron_id: str | None = Field(default=None, min_length=1)
    version: str | None = Field(default=None, min_length=1)


def _key(value: str | None) -> None:
    require_key(value)


def _db() -> str:
    """La base que diga el entorno, no la ruta por defecto de cada clase.

    Los constructores del subsistema traen `"triade/memory/triade.db"` como
    valor por defecto. Tomarlo sin mirar `TRIADE_DB_PATH` significa escribir
    siempre en la base real: un despliegue con otra ruta usaría la equivocada en
    silencio, y una prueba no puede aislarse aunque lo intente.
    """
    return os.getenv("TRIADE_DB_PATH", "triade/memory/triade.db")


@router.post("/backup/create")
def backup_create(
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.memory.encrypted_backup import EncryptedBackup

    backup = EncryptedBackup()
    created = backup.create()
    created["verification"] = backup.verify(backup.backup_dir / created["file"])
    created["retention"] = backup.enforce_retention()
    return created


@router.get("/peft/status")
def peft_status() -> dict[str, Any]:
    from triade.training.peft_canary import PeftCanaryServer

    return PeftCanaryServer().status()


@router.get("/peft/pending-approval")
def peft_pending_approval() -> dict[str, Any]:
    """Adaptadores que ya pasaron canary y esperan una aprobación humana
    de un clic. Solo lectura -- no activa nada."""
    from triade.training.peft_canary import PeftCanaryServer

    return PeftCanaryServer().pending_approval()


@router.post("/neurons/{neuron_id}/specification")
def register_neuron_specification(
    neuron_id: str,
    request: NeuronSpecificationRequest,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    """Declara qué aporta una neurona y qué puede consumir.

    Seis módulos de la fábrica leen `neuron_specifications` y **ningún camino de
    producción la escribía**: `register()` sólo lo llamaban los tests. Por eso la
    cadena de auto-mejora muere en `especificación no registrada`, con las 37
    neuronas de la base viva sin una sola fila.

    Va con firma y no en un worker a propósito: declarar que una neurona aporta
    una capacidad y autorizarle un presupuesto es gobernanza. Lo descriptivo se
    deriva de la neurona registrada para que no haya dos descripciones de lo
    mismo.
    """
    _key(x_triade_api_key)
    from triade.neuron_factory import NeuronSpecificationStore, ResourceBudget

    try:
        return {
            "status": "ok",
            "specification": NeuronSpecificationStore(
                _db()
            ).register_for_existing_neuron(
                neuron_id,
                version=request.version,
                component=request.component,
                provides_capabilities=tuple(request.provides_capabilities),
                requires_capabilities=tuple(request.requires_capabilities),
                evaluation_suites=tuple(request.evaluation_suites),
                rollback_policy=request.rollback_policy,
                critical=request.critical,
                owner=request.approved_by,
                resource_budget=ResourceBudget(
                    max_memory_mb=request.max_memory_mb,
                    max_runtime_seconds=request.max_runtime_seconds,
                    max_storage_mb=request.max_storage_mb,
                ),
            ),
        }
    except (KeyError, ValueError) as exc:
        return {"status": "blocked", "reason": str(exc)}


@router.get("/pending-human-gates")
def pending_human_gates_route() -> dict[str, Any]:
    """Todo lo que espera una firma humana, en un solo sitio.

    Las compuertas estaban repartidas y sólo una se veía: el adaptador PEFT
    tenía tarjeta en Cabina Viva y la aprobación de una propuesta de auto-mejora
    sólo existía como ruta HTTP, sin ningún sitio donde apareciera que estaba
    esperando. Una compuerta que nadie ve no gobierna: deja el circuito parado
    con aspecto de estar funcionando.

    Sólo lee. Firmar sigue siendo una llamada explícita al endpoint de cada
    subsistema, con un nombre propio detrás.
    """
    from triade.core.human_gates import pending_human_gates

    return pending_human_gates(_db())


@router.post("/peft/canary")
def peft_canary(
    request: CanaryRequest,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.training.peft_canary import PeftCanaryServer

    return PeftCanaryServer().generate(
        request.adapter_path, request.prompt, max_new_tokens=request.max_new_tokens
    )


@router.post("/peft/activate")
def peft_activate(
    request: AdapterDecision,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.training.peft_canary import PeftCanaryServer

    return PeftCanaryServer().activate(
        request.adapter_path, approved_by=request.approved_by
    )


@router.post("/peft/rollback")
def peft_rollback(
    approved_by: str,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.training.peft_canary import PeftCanaryServer

    return PeftCanaryServer().rollback(approved_by=approved_by)


@router.get("/peft/governed/status")
def governed_peft_status() -> dict[str, Any]:
    """Estado del registro gobernado canónico, distinto del slot PEFT legacy."""
    from triade.training.serving_governance import GovernedPeftServing

    return GovernedPeftServing(_db(), "artifacts/adapters").status()


@router.post("/peft/governed/activate")
def governed_peft_activate(
    request: GovernedAdapterDecision,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    """Firma la versión que fue inscrita y medida por la gobernanza canónica."""
    _key(x_triade_api_key)
    from triade.training.serving_governance import GovernedPeftServing

    return GovernedPeftServing(_db(), "artifacts/adapters").activate(
        request.version_id, approved_by=request.approved_by
    )


@router.post("/peft/governed/rollback")
def governed_peft_rollback(
    request: EvolutionApproval,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.training.serving_governance import GovernedPeftServing

    return GovernedPeftServing(_db(), "artifacts/adapters").rollback(
        approved_by=request.approved_by
    )


@router.post("/peft/governed/retire-incompatible")
def governed_peft_retire_incompatible(
    request: GovernedAdapterDecision,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    """Retira con firma un canary que no casa con ningún modelo servido."""
    _key(x_triade_api_key)
    from triade.training.serving_governance import GovernedPeftServing

    return GovernedPeftServing(_db(), "artifacts/adapters").retire_incompatible(
        request.version_id, approved_by=request.approved_by
    )


@router.post("/lora/jobs")
def schedule_lora(
    request: LoraRequest,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.core.goal_orchestrator import GoalOrchestrator

    return GoalOrchestrator().schedule_lora(
        dataset_path=request.dataset_path,
        approved_by=request.approved_by,
        base_model=request.base_model,
        max_steps=request.max_steps,
        ood_path=request.ood_path,
        forgetting_path=request.forgetting_path,
        maximum_gpu_minutes=request.maximum_gpu_minutes,
    )


@router.post("/engineering/propose")
def engineering_propose(
    request: EvolutionRequest,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.evolution.engineering_worker import EngineeringEvolutionWorker

    return EngineeringEvolutionWorker().propose(
        request.objective, request.hypothesis, request.patch
    )


@router.post("/engineering/{evolution_id}/approve")
def engineering_approve(
    evolution_id: str,
    request: EvolutionApproval,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.evolution.engineering_worker import EngineeringEvolutionWorker

    return EngineeringEvolutionWorker().approve_and_commit(
        evolution_id, approved_by=request.approved_by
    )


@router.post("/engineering/{evolution_id}/deploy")
def engineering_deploy(
    evolution_id: str,
    request: EvolutionApproval,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.evolution.engineering_worker import EngineeringEvolutionWorker

    return EngineeringEvolutionWorker().deploy(
        evolution_id, approved_by=request.approved_by
    )


@router.post("/engineering/{evolution_id}/rollback")
def engineering_rollback(
    evolution_id: str,
    request: EvolutionApproval,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.evolution.engineering_worker import EngineeringEvolutionWorker

    return EngineeringEvolutionWorker().rollback(
        evolution_id, approved_by=request.approved_by
    )


@router.get("/engineering/watchdog")
def engineering_watchdog() -> dict[str, Any]:
    from triade.evolution.engineering_worker import EngineeringEvolutionWorker

    return EngineeringEvolutionWorker().watchdog()


@router.get("/education/status")
def education_status() -> dict[str, Any]:
    from triade.neurons import NeuronEducationCycle

    return NeuronEducationCycle().status()


# ── Automejora gobernada ────────────────────────────────────────────────
#
# `triade/self_improvement/` estaba completo —store, bridge, canary,
# orquestador, aprendizaje del fallo— y sin ninguna puerta. Su ciclo exige por
# diseño que **un humano decida la dirección**: `bridge.create_candidate` obliga
# a que la propuesta esté `approved`, y `approve()` a que haya un `approved_by`.
# Es la separación correcta —el humano elige qué se intenta, la máquina hace la
# verificación rigurosa— pero no existía forma de aprobar nada: ni endpoint ni
# CLI. Una capacidad gobernada que nadie podía ejercer.
#
# Por eso `improvement_signals`, `improvement_proposals` e `improvement_canaries`
# no existían siquiera como tablas, y `self_improvement_evaluation` y
# `self_improvement_canary_observation` figuraban entre los task types nunca
# ejecutados: su handler cuelga de este gate.
#
# Estas rutas no añaden lógica: exponen lo que ya estaba escrito, en el mismo
# router y con la misma llave que `/engineering/*`, que es el subsistema hermano
# —aquél cambia código; éste cambia comportamiento medido contra la suite de
# vitalidad—. Ninguna de las dos promueve a estable por su cuenta.


@router.get("/improvement/status")
def improvement_status(
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.self_improvement.orchestrator import SelfImprovementOrchestrator

    # Preguntar no puede cambiar nada. La primera versión instanciaba el store
    # para que el esquema existiera, y eso convertía un `GET` en una migración:
    # consultar el estado creaba diez tablas vacías, que además pasaban a contar
    # como deuda por el mero hecho de haber mirado. Un observador que altera lo
    # observado no sirve para observar.
    #
    # El esquema lo crea quien escribe —registrar una señal o una propuesta—,
    # que es cuando el subsistema empieza a existir de verdad.
    #
    # No basta con capturar el error: construir el orquestador **ya** crea
    # esquema, porque su bridge y su canary lo hacen en `__init__`. Por eso la
    # existencia se comprueba antes, sobre el catálogo y en `mode=ro`, y sólo se
    # construye cuando hay algo que resumir.
    with sqlite3.connect(f"file:{_db()}?mode=ro", uri=True) as conn:
        existe = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' "
            "AND name='improvement_proposals'"
        ).fetchone()
    if existe is None:
        return {
            "status": "ok",
            "initialized": False,
            "detail": "sin señales ni propuestas: el subsistema aún no se ha usado",
        }
    return {
        "status": "ok",
        "initialized": True,
        "snapshot": SelfImprovementOrchestrator(_db()).snapshot(),
    }


@router.post("/improvement/signals")
def improvement_register_signal(
    request: ImprovementSignalRequest,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.self_improvement.contracts import ImprovementSignal
    from triade.self_improvement.store import ImprovementStore

    payload = request.model_dump()
    signal = ImprovementSignal(
        signal_id=f"signal-{uuid4().hex[:16]}",
        **payload,
    )
    return {"status": "ok", "signal": ImprovementStore(_db()).register_signal(signal)}


@router.post("/improvement/proposals")
def improvement_create_proposal(
    request: ImprovementProposalRequest,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.self_improvement.contracts import ImprovementProposal
    from triade.self_improvement.store import ImprovementStore

    proposal = ImprovementProposal(
        proposal_id=f"proposal-{uuid4().hex[:16]}",
        requires_human_approval=True,
        **request.model_dump(),
    )
    return {
        "status": "ok",
        "proposal": ImprovementStore(_db()).create_proposal(proposal),
    }


@router.post("/improvement/proposals/{proposal_id}/approve")
def improvement_approve(
    proposal_id: str,
    request: EvolutionApproval,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    """La firma humana que el ciclo exige y que no se podía dar."""
    _key(x_triade_api_key)
    from triade.self_improvement.bridge import ImprovementNeuronFactoryBridge

    # El bridge protege el gate con excepciones —`approved_by` vacío o propuesta
    # que no está `open`—. Sin traducirlas, una firma inválida sale como 500 y
    # parece un fallo del servidor en vez de la negativa que es.
    try:
        aprobada = ImprovementNeuronFactoryBridge(_db()).approve(
            proposal_id, approved_by=request.approved_by
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "proposal": aprobada}


@router.post("/improvement/proposals/{proposal_id}/target")
def improvement_assign_target(
    proposal_id: str,
    request: ImprovementTargetDecision,
    x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key"),
) -> dict[str, Any]:
    """Asigna de forma nominal la neurona que intentará la mejora."""
    _key(x_triade_api_key)
    from triade.self_improvement.bridge import ImprovementNeuronFactoryBridge

    try:
        proposal = ImprovementNeuronFactoryBridge(_db()).assign_target(
            proposal_id,
            neuron_id=request.neuron_id,
            version=request.version,
            assigned_by=request.assigned_by,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"status": "ok", "proposal": proposal}
