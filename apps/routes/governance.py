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


class LoraRequest(BaseModel):
    dataset_path: str
    approved_by: str = Field(min_length=1)
    base_model: str = "Qwen/Qwen2.5-0.5B-Instruct"
    max_steps: int = Field(default=20, ge=1, le=100)


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
