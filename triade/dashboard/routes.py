"""T-021 — Dashboard API: endpoints para todos los subsistemas de Tríade Ω."""

import json
from fastapi import APIRouter, HTTPException
from triade.core.contracts import utc_now

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/status")
def dashboard_status():
    """Status general de todos los subsistemas."""
    return {
        "status": "operational",
        "system": "Tríade Ω",
        "version": "1.0.0",
        "timestamp": utc_now(),
        "subsystems": {
            "central": {"status": "active", "description": "Planificación y razonamiento"},
            "hypothalamus": {"status": "active", "description": "Regulación emocional y prioridades"},
            "crystal": {"status": "active", "description": "Identidad y continuidad"},
            "qualia": {"status": "active", "description": "Experiencia y significado"},
            "bodega": {"status": "active", "description": "Memoria y conocimiento"},
            "scheduler": {"status": "active", "description": "Ejecución de trabajo"},
            "workers": {"status": "active", "description": "Procesamiento paralelo"},
            "neuron_factory": {"status": "active", "description": "Creación de neuronas"},
            "learning": {"status": "active", "description": "Pipeline de aprendizaje"},
            "federation": {"status": "active", "description": "Multi-nodo"},
            "constitution": {"status": "active", "description": "Gobernanza"},
            "monitor": {"status": "active", "description": "Monitoreo del sistema"},
            "models": {"status": "active", "description": "Router de modelos"},
            "triadeos": {"status": "active", "description": "Sistema operativo cognitivo"},
        },
    }


@router.get("/metrics")
def dashboard_metrics():
    """Métricas agregadas de todos los subsistemas."""
    metrics = {"timestamp": utc_now()}
    try:
        from triade.core.system_monitor import SystemMonitor
        mon = SystemMonitor()
        snap = mon.latest_snapshot()
        if snap:
            metrics["system"] = {
                "cpu": snap.get("cpu_percent", 0),
                "ram": snap.get("ram_percent", 0),
                "gpu": snap.get("gpu_percent", 0),
                "gpu_temp": snap.get("gpu_temp_c", 0),
                "disk": snap.get("disk_percent", 0),
            }
    except Exception:
        metrics["system"] = {}

    try:
        from triade.workers.advanced_scheduler import AdvancedScheduler
        sch = AdvancedScheduler()
        metrics["scheduler"] = sch.doctor()
    except Exception:
        metrics["scheduler"] = {}

    try:
        from triade.constitution.enforcer import ConstitutionEnforcer
        ce = ConstitutionEnforcer()
        metrics["constitution"] = ce.doctor()
    except Exception:
        metrics["constitution"] = {}

    return metrics


@router.get("/subsystem/{name}")
def subsystem_status(name: str):
    """Status de un subsistema específico."""
    try:
        if name == "central":
            from triade.core.central import Central
            c = Central()
            return {"subsystem": "central", "status": "active", "info": {}}
        elif name == "scheduler":
            from triade.workers.advanced_scheduler import AdvancedScheduler
            return {"subsystem": "scheduler", "status": "active", "info": AdvancedScheduler().doctor()}
        elif name == "constitution":
            from triade.constitution.enforcer import ConstitutionEnforcer
            return {"subsystem": "constitution", "status": "active", "info": ConstitutionEnforcer().doctor()}
        elif name == "monitor":
            from triade.core.system_monitor import SystemMonitor
            return {"subsystem": "monitor", "status": "active", "info": SystemMonitor().doctor()}
        elif name == "federation":
            from triade.federation.federation_advanced import FederationAdvanced
            return {"subsystem": "federation", "status": "active", "info": FederationAdvanced().doctor()}
        elif name == "models":
            from triade.models.smart_router import SmartModelRouter
            return {"subsystem": "models", "status": "active", "info": SmartModelRouter().doctor()}
        elif name == "neuron_factory":
            from triade.neuron_factory.training import TrainingPipeline
            return {"subsystem": "neuron_factory", "status": "active", "info": TrainingPipeline().doctor()}
        else:
            raise HTTPException(status_code=404, detail=f"Unknown subsystem: {name}")
    except HTTPException:
        raise
    except Exception as e:
        return {"subsystem": name, "status": "error", "error": str(e)}


@router.get("/constitution")
def constitution_status():
    """Status de la constitución y violaciones."""
    try:
        from triade.constitution.enforcer import ConstitutionEnforcer
        ce = ConstitutionEnforcer()
        return {
            "doctor": ce.doctor(),
            "open_violations": ce.open_violations(),
            "article_summary": ce.article_summary(),
        }
    except Exception as e:
        return {"error": str(e)}


@router.get("/pulse")
def pulse_status():
    """Pulso del sistema: heartbeat y métricas en tiempo real."""
    try:
        from triade.core.system_monitor import SystemMonitor
        mon = SystemMonitor()
        snap = mon.latest_snapshot()
        return {"pulse": "active", "last_snapshot": snap, "timestamp": utc_now()}
    except Exception as e:
        return {"pulse": "error", "error": str(e)}


@router.get("/hypothalamus")
def hypothalamus_status():
    """Hipotálamo: regulación emocional y prioridades."""
    try:
        from triade.hypothalamus.vice_virtue import ViceVirtueState
        vvs = ViceVirtueState()
        virtue_name, virtue_score = vvs.dominant_virtue
        sin_name, sin_score = vvs.dominant_sin
        return {"subsystem": "hypothalamus", "status": "active",
                "dominant_virtue": virtue_name, "virtue_score": virtue_score,
                "dominant_sin": sin_name, "sin_score": sin_score}
    except Exception as e:
        return {"subsystem": "hypothalamus", "status": "error", "error": str(e)}


@router.get("/crystal")
def crystal_status():
    """Cristal: identidad y continuidad."""
    try:
        from triade.qualia.continuity import ContinuityEngine
        ce = ContinuityEngine()
        return {"subsystem": "crystal", "status": "active", "doctor": ce.doctor()}
    except Exception as e:
        return {"subsystem": "crystal", "status": "error", "error": str(e)}


@router.get("/bodega")
def bodega_status():
    """Bodega: memoria y conocimiento."""
    try:
        from triade.memory.semantic_store import SemanticMemoryStore
        ss = SemanticMemoryStore()
        return {"subsystem": "bodega", "status": "active", "doctor": ss.doctor()}
    except Exception as e:
        return {"subsystem": "bodega", "status": "error", "error": str(e)}


@router.get("/workers")
def workers_status():
    """Workers: procesamiento paralelo."""
    try:
        from triade.workers.worker_supervisor import WorkerSupervisor
        ws = WorkerSupervisor()
        return {"subsystem": "workers", "status": "active", "doctor": ws.doctor()}
    except Exception as e:
        return {"subsystem": "workers", "status": "error", "error": str(e)}


@router.get("/recursos")
def recursos_status():
    """Recursos: compartidos entre nodos."""
    try:
        from triade.federation.federation_advanced import FederationAdvanced
        fed = FederationAdvanced()
        return {"subsystem": "recursos", "status": "active",
                "resources": fed.available_resources()}
    except Exception as e:
        return {"subsystem": "recursos", "status": "error", "error": str(e)}


@router.get("/learning")
def learning_status():
    """Aprendizaje: pipeline de aprendizaje continuo."""
    try:
        from triade.learning.causal_learning import CausalLearningEngine
        cle = CausalLearningEngine()
        return {"subsystem": "learning", "status": "active", "doctor": cle.doctor()}
    except Exception as e:
        return {"subsystem": "learning", "status": "error", "error": str(e)}


@router.get("/health")
def health_check():
    """Health check rápido."""
    return {"status": "healthy", "timestamp": utc_now(), "version": "1.0.0"}


@router.get("/events")
def events_status():
    """Eventos del sistema: event engine y reglas activas."""
    try:
        from triade.os.event_engine import EventEngine
        ee = EventEngine()
        rules = ee.get_rules() if hasattr(ee, 'get_rules') else []
        return {"subsystem": "events", "status": "active",
                "rules_count": len(rules), "doctor": ee.doctor()}
    except Exception as e:
        return {"subsystem": "events", "status": "error", "error": str(e)}


@router.get("/audit")
def audit_status():
    """Auditoría: trails de todas las operaciones."""
    try:
        audit_data = {}
        try:
            from triade.constitution.enforcer import ConstitutionEnforcer
            ce = ConstitutionEnforcer()
            audit_data["constitution"] = ce.doctor()
        except Exception:
            pass
        try:
            from triade.sandbox.enhanced_tool_registry import EnhancedToolRegistry
            etr = EnhancedToolRegistry()
            audit_data["tool_audit"] = etr.audit_log(limit=20)
        except Exception:
            pass
        try:
            from triade.memory.replacement_tracker import ReplacementTracker
            rt = ReplacementTracker()
            audit_data["replacements"] = rt.rollback_history(limit=20)
        except Exception:
            pass
        return {"subsystem": "audit", "status": "active", "audit_data": audit_data}
    except Exception as e:
        return {"subsystem": "audit", "status": "error", "error": str(e)}
