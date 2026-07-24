"""Neurona Central — Planeación estructurada con PlanGraph completo.

Recibe: señales del Hipotálamo, QualiaPacket, restricciones de Constitución,
recursos del sistema, y memoria recuperada.
Produce: plan ejecutable con PlanStep en máquina de estados real,
presupuestos por paso, delegación, métricas de cierre, y persistencia.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from triade.core.contracts import utc_now
from triade.models.ollama_client import OllamaClient

log = logging.getLogger(__name__)

VALID_STATES = ("pending", "ready", "running", "completed", "failed", "rolled_back", "blocked")


@dataclass
class StepBudget:
    cpu_seconds: float = 15.0
    ram_mb: float = 256.0
    gpu_seconds: float = 0.0
    timeout_seconds: float = 30.0
    tokens_max: int = 2000
    used_cpu_seconds: float = 0.0
    used_ram_mb: float = 0.0
    used_gpu_seconds: float = 0.0
    used_tokens: int = 0

    def can_proceed(self) -> bool:
        return (self.used_cpu_seconds < self.cpu_seconds and
                self.used_ram_mb < self.ram_mb and
                self.used_tokens < self.tokens_max)

    def consume(self, cpu: float = 0.0, ram: float = 0.0, gpu: float = 0.0, tokens: int = 0) -> None:
        self.used_cpu_seconds += cpu
        self.used_ram_mb += ram
        self.used_gpu_seconds += gpu
        self.used_tokens += tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "cpu_seconds": self.cpu_seconds,
            "ram_mb": self.ram_mb,
            "gpu_seconds": self.gpu_seconds,
            "timeout_seconds": self.timeout_seconds,
            "tokens_max": self.tokens_max,
            "used_cpu_seconds": round(self.used_cpu_seconds, 2),
            "used_ram_mb": round(self.used_ram_mb, 2),
            "used_gpu_seconds": round(self.used_gpu_seconds, 2),
            "used_tokens": self.used_tokens,
        }


@dataclass
class PlanStep:
    id: str = ""
    description: str = ""
    step_type: str = "action"
    state: str = "pending"
    priority: int = 2
    dependencies: list[str] = field(default_factory=list)
    assigned_to: str = "central"
    budget: StepBudget = field(default_factory=StepBudget)
    result: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    retry_count: int = 0
    max_retries: int = 2
    rollback_data: dict[str, Any] = field(default_factory=dict)

    def is_ready(self, completed_ids: set[str]) -> bool:
        if self.state != "pending":
            return False
        return all(dep in completed_ids for dep in self.dependencies)

    def start(self) -> None:
        self.state = "running"
        self.started_at = utc_now()

    def complete(self, result: dict[str, Any]) -> None:
        self.state = "completed"
        self.result = result
        self.completed_at = utc_now()

    def fail(self, error: str) -> None:
        self.state = "failed"
        self.error = error
        self.completed_at = utc_now()

    def rollback(self, data: dict[str, Any] | None = None) -> None:
        self.state = "rolled_back"
        self.rollback_data = data or {}
        self.completed_at = utc_now()

    def block(self, reason: str = "") -> None:
        self.state = "blocked"
        self.error = reason
        self.completed_at = utc_now()

    def can_retry(self) -> bool:
        return self.state == "failed" and self.retry_count < self.max_retries

    def retry(self) -> None:
        self.state = "pending"
        self.retry_count += 1
        self.error = ""
        self.started_at = ""
        self.completed_at = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "step_type": self.step_type,
            "state": self.state,
            "priority": self.priority,
            "dependencies": list(self.dependencies),
            "assigned_to": self.assigned_to,
            "budget": self.budget.to_dict(),
            "result": dict(self.result),
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "rollback_data": dict(self.rollback_data),
        }


@dataclass
class PlanGraph:
    plan_id: str = ""
    goal: str = ""
    steps: list[PlanStep] = field(default_factory=list)
    total_budget_cpu: float = 60.0
    total_budget_ram: float = 1024.0
    total_budget_gpu: float = 0.0
    total_budget_tokens: int = 10000
    created_at: str = ""
    completed_at: str = ""
    status: str = "created"
    metrics: dict[str, Any] = field(default_factory=dict)
    constitution_applied: list[dict[str, Any]] = field(default_factory=list)
    delegation_log: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = utc_now()
        if not self.plan_id:
            self.plan_id = f"plan-{int(__import__('time').time() * 1000)}"

    def add_step(self, step: PlanStep) -> None:
        self.steps.append(step)

    def get_step(self, step_id: str) -> PlanStep | None:
        for s in self.steps:
            if s.id == step_id:
                return s
        return None

    @property
    def completed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.state == "completed"]

    @property
    def failed_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.state == "failed"]

    @property
    def pending_steps(self) -> list[PlanStep]:
        return [s for s in self.steps if s.state == "pending"]

    @property
    def ready_steps(self) -> list[PlanStep]:
        completed_ids = {s.id for s in self.completed_steps}
        return [s for s in self.steps if s.is_ready(completed_ids)]

    @property
    def all_completed(self) -> bool:
        return all(s.state in ("completed", "rolled_back") for s in self.steps)

    @property
    def has_failures(self) -> bool:
        return any(s.state == "failed" for s in self.steps)

    def compute_metrics(self) -> dict[str, Any]:
        total = len(self.steps)
        completed = len(self.completed_steps)
        failed = len(self.failed_steps)
        rolled_back = sum(1 for s in self.steps if s.state == "rolled_back")
        blocked = sum(1 for s in self.steps if s.state == "blocked")
        total_cpu_used = sum(s.budget.used_cpu_seconds for s in self.steps)
        total_tokens_used = sum(s.budget.used_tokens for s in self.steps)
        self.metrics = {
            "total_steps": total,
            "completed": completed,
            "failed": failed,
            "rolled_back": rolled_back,
            "blocked": blocked,
            "completion_rate": round(completed / max(total, 1), 4),
            "failure_rate": round(failed / max(total, 1), 4),
            "total_cpu_used_seconds": round(total_cpu_used, 2),
            "total_tokens_used": total_tokens_used,
            "total_cpu_budget": self.total_budget_cpu,
            "total_tokens_budget": self.total_budget_tokens,
        }
        return self.metrics

    def close(self) -> dict[str, Any]:
        self.completed_at = utc_now()
        self.status = "completed" if self.all_completed else "failed" if self.has_failures else "partial"
        self.compute_metrics()
        return self.metrics

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metrics": self.metrics,
            "constitution_applied": list(self.constitution_applied),
            "delegation_log": list(self.delegation_log),
            "budgets": {
                "total_cpu": self.total_budget_cpu,
                "total_ram": self.total_budget_ram,
                "total_gpu": self.total_budget_gpu,
                "total_tokens": self.total_budget_tokens,
            },
        }


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS plan_graphs (
    plan_id        TEXT PRIMARY KEY,
    goal           TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'created',
    steps_json     TEXT NOT NULL DEFAULT '[]',
    metrics_json   TEXT NOT NULL DEFAULT '{}',
    constitution_json TEXT NOT NULL DEFAULT '[]',
    delegation_json   TEXT NOT NULL DEFAULT '[]',
    created_at     TEXT NOT NULL,
    completed_at   TEXT
);
CREATE INDEX IF NOT EXISTS pg_status ON plan_graphs(status);
CREATE INDEX IF NOT EXISTS pg_created ON plan_graphs(created_at);
"""


class Central:
    """Planeador y generador de salida con PlanGraph estructurado."""

    INTERNAL_AUDIT_TERMS = {
        "audita", "auditoría", "auditoria", "analiza el run", "analiza este run",
        "diagnóstico técnico", "diagnostico tecnico", "debug", "trazabilidad",
        "q_crystal", "cristal", "hipotálamo", "hipotalamo", "pv7",
        "paquete cognitivo", "reporte interno", "señales internas", "senales internas",
    }

    TRIAD_IDENTITY_CORE = (
        "Tríade Ω no es un asistente genérico: es una arquitectura cognitiva modular local en construcción verificable. "
        "Sus neuronas operativas principales son: Neurona Central, que decide, estructura, planifica y coordina; "
        "Hipotálamo Emocional, que interpreta tono, intención, riesgo, urgencia y señales relacionales; "
        "Bodega de Almacenamiento, que conserva memoria, evidencias, runs y conocimiento autorizado; "
        "Cristal Morfológico, que regula ética, profundidad, creatividad, relación, estabilidad y continuidad; "
        "Federación/Nodos, que conecta dispositivos o sistemas autorizados; y Aprendizaje en segundo plano, "
        "que registra candidatos post-run y propuestas sin consolidarlas como verdad estable hasta revisión humana. "
        "En full_local_guarded puede investigar la web cuando el usuario lo pide explícitamente."
    )

    def __init__(self, model_client: OllamaClient | None = None, central_model: str = "qwen2.5:3b-instruct") -> None:
        self.model_client = model_client
        self.central_model = central_model
        self._conn: sqlite3.Connection | None = None

    def init_db(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA_SQL)

    def save_plan(self, graph: PlanGraph) -> None:
        if not self._conn:
            return
        self._conn.execute(
            """INSERT OR REPLACE INTO plan_graphs
               (plan_id, goal, status, steps_json, metrics_json, constitution_json,
                delegation_json, created_at, completed_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (graph.plan_id, graph.goal, graph.status,
             json.dumps([s.to_dict() for s in graph.steps], default=str),
             json.dumps(graph.metrics, default=str),
             json.dumps(graph.constitution_applied, default=str),
             json.dumps(graph.delegation_log, default=str),
             graph.created_at, graph.completed_at or None),
        )
        self._conn.commit()

    def load_plan(self, plan_id: str) -> PlanGraph | None:
        if not self._conn:
            return None
        row = self._conn.execute(
            "SELECT * FROM plan_graphs WHERE plan_id=?", (plan_id,)
        ).fetchone()
        if not row:
            return None
        steps_data = json.loads(row["steps_json"])
        steps = []
        for sd in steps_data:
            budget = StepBudget(**sd.get("budget", {}))
            steps.append(PlanStep(
                id=sd["id"], description=sd["description"],
                step_type=sd.get("step_type", "action"),
                state=sd.get("state", "pending"),
                priority=sd.get("priority", 2),
                dependencies=sd.get("dependencies", []),
                assigned_to=sd.get("assigned_to", "central"),
                budget=budget, result=sd.get("result", {}),
                error=sd.get("error", ""),
                started_at=sd.get("started_at", ""),
                completed_at=sd.get("completed_at", ""),
                retry_count=sd.get("retry_count", 0),
                max_retries=sd.get("max_retries", 2),
                rollback_data=sd.get("rollback_data", {}),
            ))
        return PlanGraph(
            plan_id=row["plan_id"], goal=row["goal"],
            steps=steps, status=row["status"],
            metrics=json.loads(row["metrics_json"]),
            constitution_applied=json.loads(row["constitution_json"]),
            delegation_log=json.loads(row["delegation_json"]),
            created_at=row["created_at"],
            completed_at=row["completed_at"] or "",
        )

    def _build_plan_graph(
        self,
        run_id: str,
        text_steps: list[str],
        signals: Any,
        crystal: Any,
        constitution_constraints: list[dict[str, Any]] | None = None,
    ) -> PlanGraph:
        graph = PlanGraph(goal=f"run:{run_id}")
        for idx, text in enumerate(text_steps):
            step_type = self._classify_step_type(text)
            priority = 2 if idx < 3 else 3
            deps: list[str] = []
            if idx > 0 and step_type != "observation":
                deps.append(f"step-{idx - 1}")
            assigned_to = "central"
            if step_type == "delegation":
                assigned_to = "neurona_creadora"
            budget = StepBudget(
                cpu_seconds=15.0 if step_type == "action" else 10.0,
                timeout_seconds=20.0 if step_type == "action" else 15.0,
            )
            step = PlanStep(
                id=f"step-{idx}", description=text,
                step_type=step_type, priority=priority,
                dependencies=deps, assigned_to=assigned_to,
                budget=budget,
            )
            graph.add_step(step)
        if constitution_constraints:
            graph.constitution_applied = constitution_constraints
        return graph

    @staticmethod
    def _classify_step_type(text: str) -> str:
        lower = text.lower()
        if any(w in lower for w in ["delega", "neurona", "candidata"]):
            return "delegation"
        if any(w in lower for w in ["verif", "valid", "chequea"]):
            return "verification"
        if any(w in lower for w in ["analiza", "evalúa", "evaluar", "lee"]):
            return "analysis"
        if any(w in lower for w in ["observa", "mira", "revisa"]):
            return "observation"
        return "action"

    def plan(
        self,
        input_packet: Any,
        signals: Any,
        memory: Any,
        crystal: Any,
        constitution_constraints: list[dict[str, Any]] | None = None,
    ) -> Any:
        text_steps = self._chain_of_thought(input_packet, signals, memory, crystal)
        text_steps += [
            "Leer entrada del usuario.",
            "Usar señales del Hipotálamo.",
            "Consultar memoria disponible.",
            "Aplicar regulación del Cristal.",
        ]
        if constitution_constraints:
            for c in constitution_constraints:
                text_steps.append(f"Respetar restricción constitucional: {c.get('article', '?')}")

        graph = self._build_plan_graph(
            input_packet.run_id, text_steps, signals, crystal,
            constitution_constraints,
        )

        from triade.core.contracts import PlanPacket
        from triade.core.plan_rollback import PlanRollback

        q_crystal = getattr(crystal, "q_crystal", 0.5)
        temporal = getattr(crystal, "temporal_status", "stable")
        goal = f"Atender intención: {getattr(signals, 'intent', 'unknown')} | q_crystal={q_crystal} | temporal={temporal}"
        graph.goal = goal

        return PlanPacket(
            run_id=input_packet.run_id,
            goal=goal,
            steps=[s.description for s in graph.steps],
            structured_steps=graph.steps,
            tools=[],
            safety_required=True,
            budget=None,
            rollback=PlanRollback(plan_id=graph.plan_id),
        )

    def _chain_of_thought(
        self, input_packet: Any, signals: Any, memory: Any, crystal: Any,
    ) -> list[str]:
        if self.model_client is None:
            return self._chain_of_thought_rules(input_packet, signals, memory, crystal)
        try:
            context = json.dumps({
                "user_input": input_packet.user_input[:500],
                "intent": signals.intent,
                "risk": signals.risk,
                "urgency": signals.urgency,
            }, ensure_ascii=False)
            system = (
                "Eres Central de Tríade. Genera una cadena de razonamiento en 3-5 pasos. "
                "Formato: lista de strings, uno por paso."
            )
            result = self.model_client.generate(
                self.central_model,
                prompt=f"Entrada:\n{context}\n\nCadena de razonamiento:",
                system=system,
            )
            if result.ok and result.text:
                steps = self._parse_reasoning_steps(result.text)
                if steps:
                    return steps[:7]
        except Exception as exc:
            log.warning("Central CoT failed, using rules: %s", exc)
        return self._chain_of_thought_rules(input_packet, signals, memory, crystal)

    def _chain_of_thought_rules(self, input_packet: Any, signals: Any, memory: Any, crystal: Any) -> list[str]:
        steps: list[str] = []
        q_crystal = getattr(crystal, "q_crystal", 0.5)
        stability = getattr(crystal, "stability", 0.5)
        temporal = getattr(crystal, "temporal_status", "baseline")
        if hasattr(signals, "risk") and signals.risk in {"high", "critical"}:
            steps.append("Evaluar riesgo elevado.")
        if q_crystal < 0.50:
            steps.append("Cristal bajo: máxima prudencia.")
        if hasattr(signals, "urgency") and signals.urgency == "high":
            steps.append("Urgencia alta: respuesta directa.")
        if memory.semantic_matches:
            steps.append(f"Memoria semántica: {len(memory.semantic_matches)} coincidencia(s).")
        bgc = None
        ctx = getattr(input_packet, "context", {})
        if isinstance(ctx, dict):
            bgc = ctx.get("bodega_global_context")
        if isinstance(bgc, dict) and bgc.get("status") == "ok":
            mem_conf = bgc.get("memory_confidence", "low")
            if mem_conf == "low":
                steps.append("Memoria global con confianza baja: operar con memoria limitada.")
            elif mem_conf == "medium":
                steps.append("Memoria global con confianza media: usar contexto con cautela.")
            contradictions = bgc.get("contradictions") or []
            if contradictions:
                steps.append(f"Se detectaron {len(contradictions)} contradicción(es) en memoria.")
            stable_audit = bgc.get("stable_audit_summary") or {}
            if stable_audit.get("stable_needs_review", 0) > 0:
                steps.append("Neuronas stable requieren revisión de evidencia.")
        if temporal in {"critical", "degrading"}:
            steps.append("Reforzar prudencia por degradación temporal y registrar alerta.")
        elif temporal == "improving":
            steps.append("Sostener mejora temporal.")
        if q_crystal < 0.40:
            steps.append("Responder con prudencia elevada.")
        elif q_crystal >= 0.70 and stability >= 0.65 and temporal not in {"critical", "degrading"}:
            steps.append("Profundizar la respuesta manteniendo trazabilidad.")
        else:
            steps.append("Producir respuesta verificable.")
        if not steps:
            steps.append("Analizar entrada y responder.")
        return steps

    @staticmethod
    def _parse_reasoning_steps(text: str) -> list[str]:
        steps: list[str] = []
        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            cleaned = re.sub(r"^[\d\.\-\*]+\s*", "", line).strip()
            if cleaned:
                steps.append(cleaned)
        return steps

    def execute_plan_steps(self, plan: Any, *, max_steps: int = 5) -> dict[str, Any]:
        structured = plan.structured_steps
        if not structured:
            return {"executed": [], "budget": None, "status": "no_structured_steps"}
        completed_ids: set[str] = set()
        executed: list[dict[str, Any]] = []
        for s in structured:
            if s.state == "completed":
                completed_ids.add(s.id)
        for step in structured:
            if len(executed) >= max_steps:
                break
            if not step.is_ready(completed_ids):
                continue
            step.start()
            result = self._simulate_step(step, plan)
            if result.get("ok"):
                step.complete(result)
                completed_ids.add(step.id)
                step.budget.consume(cpu=result.get("seconds", 0.5), tokens=result.get("tokens", 50))
            else:
                step.fail(result.get("error", "unknown"))
                if step.can_retry():
                    step.retry()
            executed.append({
                "step_id": step.id, "description": step.description,
                "status": step.state, "step_type": step.step_type,
                "assigned_to": step.assigned_to,
            })
        return {"executed": executed, "status": "ok"}

    @staticmethod
    def _simulate_step(step: PlanStep, plan: Any) -> dict[str, Any]:
        return {"ok": True, "seconds": 0.5, "tokens": 50, "message": f"Paso {step.id} completado."}

    def respond(self, input_packet: Any, signals: Any, memory: Any, crystal: Any, plan: Any) -> Any:
        from triade.core.contracts import OutputPacket
        identity = next(
            (item["value"] for item in memory.identity_matches if item.get("key") == "entity_name"),
            "Tríade Ω"
        )
        wants_audit = self._wants_internal_audit(input_packet.user_input)
        fallback = self._fallback_response(identity, input_packet, signals, crystal, wants_audit)
        if self._is_identity_or_capability_question(input_packet.user_input):
            return OutputPacket(
                run_id=input_packet.run_id,
                response=self._identity_capability_response(identity),
                actions_taken=["capability_truth_response"],
                memory_diff={"pending_persistence": True},
                status="ok", model_provider="policy",
                model_name="capability-truth", model_ok=True,
            )
        if self.model_client is None:
            return OutputPacket(
                run_id=input_packet.run_id,
                response=f"Operé sin Ollama. {fallback}",
                actions_taken=["template_fallback"],
                memory_diff={"pending_persistence": True, "degraded_no_ollama": True},
                status="ok", model_provider="template",
                model_name="template-fallback", model_ok=False,
            )
        prompt = self._build_prompt(identity, input_packet, signals, memory, crystal, plan, wants_audit)
        system = "Eres Tríade Ω. Responde en español. Conserva tu identidad."
        result = self.model_client.generate(self.central_model, prompt=prompt, system=system)
        if not result.ok or not result.text:
            return OutputPacket(
                run_id=input_packet.run_id,
                response=f"Ollama falló. {fallback}",
                actions_taken=["ollama_failed", "template_fallback"],
                memory_diff={"pending_persistence": True, "degraded_no_ollama": True},
                status="ok", model_provider="ollama",
                model_name=self.central_model, model_ok=False,
                model_error=result.error,
            )
        return OutputPacket(
            run_id=input_packet.run_id,
            response=result.text,
            actions_taken=["ollama_response"],
            memory_diff={"pending_persistence": True},
            status="ok", model_provider="ollama",
            model_name=self.central_model, model_ok=True,
        )

    @staticmethod
    def _fallback_response(identity: str, input_packet: Any, signals: Any, crystal: Any, wants_audit: bool = False) -> str:
        if not wants_audit:
            parts = [f"Soy {identity}. Recibí: «{input_packet.user_input[:200]}»."]
            return " ".join(parts)
        return (
            f"{identity} procesó run {input_packet.run_id}. "
            f"Intención: {signals.intent}. Riesgo: {signals.risk}."
        )

    @staticmethod
    def _is_identity_or_capability_question(text: str) -> bool:
        normalized = unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        patterns = [
            r"\bque eres\b",
            r"\bquien eres\b",
            r"\bpara que sirves\b",
            r"\bque puedes hacer\b",
            r"\bcomo trabajas\b",
            r"\bque neuronas tienes\b",
            r"\bcuales son tus neuronas\b",
            r"\bexplica tu mision\b",
            r"\bcual es tu mision\b",
            r"\bque es triade\b",
            r"\bque es triade omega\b",
            r"\bque eres y como trabajas\b",
            r"\bpuedes aprender\b",
            r"\bpuedes usar (?:la )?internet\b",
            r"\bpuedes (?:descargar|configurar)\b",
            r"\bpuedes crear imagenes\b",
        ]
        return any(re.search(pattern, normalized) for pattern in patterns)

    @staticmethod
    def _identity_capability_response(identity: str) -> str:
        return (
            f"Soy {identity}, un sistema cognitivo modular en construcción verificable. "
            "Sirvo para ayudarte a pensar, crear, organizar, recordar, analizar repositorios, diseñar procesos, proponer código, documentar decisiones y convertir ideas en acciones trazables.\n\n"
            "Trabajo con tres órganos principales: la Neurona Central, que planea, decide y valida; "
            "el Hipotálamo Emocional, que interpreta intención, tono, urgencia, riesgo y sensibilidad; "
            "y la Bodega de Almacenamiento, que conserva memoria, runs, evidencia e identidad operativa.\n\n"
            "Cada interacción puede convertirse en un run auditable con señales, memoria, cristal, plan, safety, salida, verificación e integridad. "
            "Aprendo registrando candidatos, evaluándolos con evidencia y consolidándolos solo después de superar controles. "
            "No soy conciencia humana: soy una arquitectura técnica evolutiva diseñada para trabajar con trazabilidad, prudencia y mejora continua."
        )

    @staticmethod
    def _wants_internal_audit(user_input: str) -> bool:
        text = user_input.lower()
        return any(term in text for term in Central.INTERNAL_AUDIT_TERMS)

    @staticmethod
    def _build_prompt(identity: str, input_packet: Any, signals: Any, memory: Any, crystal: Any, plan: Any, wants_audit: bool) -> str:
        if not wants_audit:
            safe_matches = []
            for item in memory.semantic_matches[:3]:
                content = str(item.get("content", "")).strip()[:400]
                if content:
                    safe_matches.append({"source_ref": str(item.get("source_ref", "mem")), "content": content})
            return (
                f"Identidad: {identity}\n"
                f"Usuario: {input_packet.user_input}\n"
                f"Intención: {signals.intent}\n"
                f"Riesgo: {signals.risk}\n"
                f"Memoria: {json.dumps(safe_matches, ensure_ascii=False)}\n"
                "Respuesta:"
            )
        return json.dumps({
            "identity": identity, "user_input": input_packet.user_input,
            "signals": signals.to_dict(), "crystal": crystal.to_dict(),
            "plan": plan.to_dict(), "response_mode": "internal_audit",
        }, ensure_ascii=False, indent=2)

    @staticmethod
    def _response_ignores_current_question(user_input: str, response: str) -> bool:
        user = user_input.lower()
        answer = response.lower()
        if "?" not in user or Central._is_identity_or_capability_question(user) or "como estas" in user or "cómo estás" in user:
            return False
        self_state_markers = (
            "no siento como una persona",
            "mi central coordina",
            "el hipotálamo interpreta",
            "la bodega se encarga",
            "cabina viva",
        )
        return sum(marker in answer for marker in self_state_markers) >= 2

    @staticmethod
    def _crystal_mode(crystal: Any) -> str:
        if hasattr(crystal, "temporal_status") and crystal.temporal_status in {"critical", "degrading"}:
            return "prudencia temporal reforzada"
        if hasattr(crystal, "q_crystal") and crystal.q_crystal < 0.40:
            return "prudencia elevada"
        q = getattr(crystal, "q_crystal", 0.5)
        s = getattr(crystal, "stability", 0.5)
        if q >= 0.70 and s >= 0.65:
            return "profundidad estable"
        return "equilibrio operativo"

    @staticmethod
    def _operational_awareness_response(identity: str, input_packet: Any) -> str:
        awareness = input_packet.context.get("triade_operational_awareness") if hasattr(input_packet, "context") and isinstance(input_packet.context, dict) else None
        if not isinstance(awareness, dict):
            return ""
        text = str(getattr(input_packet, "user_input", "")).lower()
        triggers = [
            "pulso", "vida", "viva", "estado", "neuron", "neurona", "acciones",
            "contadores", "ram", "host", "ollama", "doctor", "integridad", "aprendizaje",
            "misiones", "workers", "runtime", "qualia", "bodega", "central",
        ]
        if not any(term in text for term in triggers):
            return ""
        life = awareness.get("life") if isinstance(awareness.get("life"), dict) else {}
        qualia = awareness.get("qualia") if isinstance(awareness.get("qualia"), dict) else {}
        local = awareness.get("local") if isinstance(awareness.get("local"), dict) else {}
        federation = awareness.get("federation") if isinstance(awareness.get("federation"), dict) else {}
        runtime = awareness.get("runtime") if isinstance(awareness.get("runtime"), dict) else {}
        missions = awareness.get("missions") if isinstance(awareness.get("missions"), dict) else {}
        learning = awareness.get("learning") if isinstance(awareness.get("learning"), dict) else {}
        counters = life.get("counters") if isinstance(life.get("counters"), dict) else {}
        identity_state = qualia.get("identity") if isinstance(qualia.get("identity"), dict) else {}
        ethics = [item for item in (identity_state.get("ethics") or []) if item]
        ethics_text = " / ".join(str(item) for item in ethics) or "ética interna activa"
        origin_text = str(identity_state.get("creator_origin") or "origen no cargado")
        organ_names = [
            str(item.get("name"))
            for item in (qualia.get("organs") or [])
            if isinstance(item, dict) and item.get("name")
        ]
        organs_text = ", ".join(organ_names) or "órganos no reportados"
        gpu_text = ", ".join(str(item) for item in (local.get("gpu_names") or []) if item) or "sin GPU reportada"
        return (
            f"Soy {identity}. Hablo desde mi arquitectura viva. "
            f"Mi origen cargado es {origin_text}; mi ética base: {ethics_text}. "
            f"Qualia está {qualia.get('status')} con órganos: {organs_text}. "
            f"Pulso Vivo: ciclos={counters.get('cycles', 0)}, acciones={counters.get('actions_observed', 0)}. "
            f"RAM libre={local.get('ram_available_gb')} GB, tier {local.get('hardware_tier')}, "
            f"GPU {gpu_text}, Ollama={local.get('ollama_ok')}. "
            f"Federación: runtime={federation.get('runtime')}, nodos={federation.get('runtime_node_count')}. "
            f"Mi runtime interno reporta modo={runtime.get('mode', 'observe_only')}, "
            f"misiones_actives={missions.get('active_count', 0)}, "
            f"candidatos_aprendizaje={len(learning.get('recent_candidates', []))}. "
            "Central ordena, Hipotálamo modula, Bodega conserva."
        )
