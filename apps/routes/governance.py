"""Rutas administrativas de backup, LoRA y serving canary."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

from apps.routes.api import require_key

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


def _key(value: str | None) -> None:
    require_key(value)


@router.post("/backup/create")
def backup_create(x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key")) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.memory.encrypted_backup import EncryptedBackup
    backup = EncryptedBackup(); created = backup.create()
    created["verification"] = backup.verify(backup.backup_dir / created["file"])
    created["retention"] = backup.enforce_retention()
    return created


@router.get("/peft/status")
def peft_status() -> dict[str, Any]:
    from triade.training.peft_canary import PeftCanaryServer
    return PeftCanaryServer().status()


@router.post("/peft/canary")
def peft_canary(request: CanaryRequest,
                x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key")) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.training.peft_canary import PeftCanaryServer
    return PeftCanaryServer().generate(request.adapter_path, request.prompt, max_new_tokens=request.max_new_tokens)


@router.post("/peft/activate")
def peft_activate(request: AdapterDecision,
                  x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key")) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.training.peft_canary import PeftCanaryServer
    return PeftCanaryServer().activate(request.adapter_path, approved_by=request.approved_by)


@router.post("/peft/rollback")
def peft_rollback(approved_by: str,
                  x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key")) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.training.peft_canary import PeftCanaryServer
    return PeftCanaryServer().rollback(approved_by=approved_by)


@router.post("/lora/jobs")
def schedule_lora(request: LoraRequest,
                  x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key")) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.core.goal_orchestrator import GoalOrchestrator
    return GoalOrchestrator().schedule_lora(dataset_path=request.dataset_path, approved_by=request.approved_by,
                                            base_model=request.base_model, max_steps=request.max_steps)

@router.post("/engineering/propose")
def engineering_propose(request: EvolutionRequest,
                        x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key")) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.evolution.engineering_worker import EngineeringEvolutionWorker
    return EngineeringEvolutionWorker().propose(request.objective,request.hypothesis,request.patch)

@router.post("/engineering/{evolution_id}/approve")
def engineering_approve(evolution_id: str, request: EvolutionApproval,
                        x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key")) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.evolution.engineering_worker import EngineeringEvolutionWorker
    return EngineeringEvolutionWorker().approve_and_commit(evolution_id,approved_by=request.approved_by)

@router.post("/engineering/{evolution_id}/deploy")
def engineering_deploy(evolution_id: str, request: EvolutionApproval,
                       x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key")) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.evolution.engineering_worker import EngineeringEvolutionWorker
    return EngineeringEvolutionWorker().deploy(evolution_id,approved_by=request.approved_by)

@router.post("/engineering/{evolution_id}/rollback")
def engineering_rollback(evolution_id: str, request: EvolutionApproval,
                         x_triade_api_key: str | None = Header(default=None, alias="X-TRIADE-API-Key")) -> dict[str, Any]:
    _key(x_triade_api_key)
    from triade.evolution.engineering_worker import EngineeringEvolutionWorker
    return EngineeringEvolutionWorker().rollback(evolution_id,approved_by=request.approved_by)

@router.get("/engineering/watchdog")
def engineering_watchdog() -> dict[str, Any]:
    from triade.evolution.engineering_worker import EngineeringEvolutionWorker
    return EngineeringEvolutionWorker().watchdog()


@router.get("/education/status")
def education_status() -> dict[str, Any]:
    from triade.neurons import NeuronEducationCycle

    return NeuronEducationCycle().status()
