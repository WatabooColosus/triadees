"""Constitución inmutable de Tríade Ω.

Documento viviente que sella las reglas fundamentales del sistema.
Cada artículo es verificable, auditable y no puede ser modificado
sin aprobación humana explícita y rollback obligatorio.

Versión: 1.0.0
Fecha: 2026-07-24
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Article:
    article_id: str
    title: str
    text: str
    severity: str = "critical"
    immutable: bool = True
    rationale: str = ""


CONSTITUTION_VERSION = "1.0.0"

ARTICLES: tuple[Article, ...] = (
    Article(
        article_id="I",
        title="Identidad Inmutable",
        text="La identity_core es sagrada. Ninguna operación puede modificarla sin aprobación humana explícita y rollback obligatorio.",
        severity="critical",
        immutable=True,
        rationale="La identidad es la base de toda coherencia cognitiva.",
    ),
    Article(
        article_id="II",
        title="Aprendizaje Gobernado",
        text="Ninguna memoria entra en estado stable sin evidencia verificada, evaluación independiente y aprobación de al menos un camino autorizado.",
        severity="critical",
        immutable=True,
        rationale="El aprendizaje no gobernado degrada la capacidad cognitiva.",
    ),
    Article(
        article_id="III",
        title="Rollback Obligatorio",
        text="Toda capacidad crítica debe tener una política de rollback注册ada. Sin rollback, no hay promoción.",
        severity="critical",
        immutable=True,
        rationale="Sin capacidad de reversión, cada error es permanente.",
    ),
    Article(
        article_id="IV",
        title="Medición Independiente",
        text="Los embeddings y la búsqueda semántica son servicios de soporte. Nunca son el árbitro de calidad. La evaluación es independiente.",
        severity="high",
        immutable=True,
        rationale="Confundir soporte con arbitraje crea ciclos de confirmación.",
    ),
    Article(
        article_id="V",
        title="Verificación Autónoma",
        text="El Consejo de Verificación opera de forma independiente del pipeline de aprendizaje. Ningún componente se auto-verifica.",
        severity="critical",
        immutable=True,
        rationale="La auto-verificación es una contradicción lógica.",
    ),
    Article(
        article_id="VI",
        title="Shell Prohibida",
        text="Ninguna ejecución usa shell=True. Todo pasa por sandboxes whitelistados con límites de CPU, RAM, PID y tiempo.",
        severity="critical",
        immutable=True,
        rationale="Shell es la superficie de ataque más grande de un sistema autónomo.",
    ),
    Article(
        article_id="VII",
        title="Aislamiento de Capacidades",
        text="Las capacidades se evalúan de forma aislada. Una regresión en una capacidad no bloquea otras a menos que haya dependencia directa.",
        severity="high",
        immutable=True,
        rationale="El acoplamiento de fallos multiplica el impacto.",
    ),
    Article(
        article_id="VIII",
        title="Pulso Vivo",
        text="El sistema tiene un pulso jerárquico que monitorea salud, latencia, coherencia y anomalías. Sin pulso, no hay operación.",
        severity="critical",
        immutable=True,
        rationale="Un sistema sin monitoreo es un sistema ciego.",
    ),
    Article(
        article_id="IX",
        title="Conservación de Estado",
        text="Toda transición de estado es auditada. El historial completo es recuperable. No hay operaciones destructivas sin registro.",
        severity="high",
        immutable=True,
        rationale="Sin auditabilidad, no hay rendición de cuentas.",
    ),
    Article(
        article_id="X",
        title="Degradación Controlada",
        text="Cuando Ollama no está disponible, el sistema entra en modo fallback con operaciones limitadas. Nunca se detiene completamente.",
        severity="medium",
        immutable=False,
        rationale="La disponibilidad parcial es mejor que la indisponibilidad total.",
    ),
)


class Constitution:
    """Gestor de la constitución inmutable de Tríade Ω."""

    def __init__(self) -> None:
        self._articles = {a.article_id: a for a in ARTICLES}
        self._version = CONSTITUTION_VERSION

    @property
    def version(self) -> str:
        return self._version

    def get_article(self, article_id: str) -> Article | None:
        return self._articles.get(article_id)

    def list_articles(self) -> list[Article]:
        return list(ARTICLES)

    def verify(self) -> dict[str, Any]:
        errors: list[str] = []
        for article in ARTICLES:
            if not article.text.strip():
                errors.append(f"Artículo {article.article_id}: texto vacío.")
        return {
            "version": self._version,
            "total_articles": len(ARTICLES),
            "immutable_articles": sum(1 for a in ARTICLES if a.immutable),
            "critical_articles": sum(1 for a in ARTICLES if a.severity == "critical"),
            "errors": errors,
            "status": "valid" if not errors else "invalid",
            "checksum": self._checksum(),
        }

    def _checksum(self) -> str:
        content = json.dumps(
            [{"id": a.article_id, "title": a.title, "text": a.text} for a in ARTICLES],
            sort_keys=True, ensure_ascii=False,
        )
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self._version,
            "articles": [
                {
                    "id": a.article_id,
                    "title": a.title,
                    "text": a.text,
                    "severity": a.severity,
                    "immutable": a.immutable,
                    "rationale": a.rationale,
                }
                for a in ARTICLES
            ],
            "checksum": self._checksum(),
        }

    def check_operation(self, operation: str, target: str) -> dict[str, Any]:
        violations: list[str] = []
        target_lower = target.lower()
        op_lower = operation.lower()

        # Artículo I: Protección de identity_core.
        # Cualquier operación que afecte identity_core requiere aprobación explícita.
        # Se verifica con prefijos de acción concretos, no con substrings genéricos.
        if target_lower == "identity_core" or target_lower.startswith("identity_core."):
            action_prefixes = ("modify", "update", "change", "replace", "delete", "overwrite")
            if any(op_lower.startswith(prefix) or f".{prefix}" in op_lower for prefix in action_prefixes):
                violations.append(
                    "Artículo I: Modificación de identity_core requiere aprobación humana explícita y rollback obligatorio."
                )

        # Artículo II: Aprendizaje gobernado.
        # No bloqueamos por keyword — la Política II es verificada por el pipeline
        # (requiere evidencia, evaluación independiente, run_use_count >= 3, etc.).
        # Esta constitución solo actúa como referencia normativa.
        # NO se agrega violación aquí; la enforce real vive en LearningPipeline.consolidate().

        # Artículo III: Rollback obligatorio para capacidades críticas.
        if "promote" in op_lower and "critical" in target_lower:
            violations.append(
                "Artículo III: Promoción de capacidad crítica requiere rollback registrado."
            )

        # Artículo VI: Shell explícita está prohibida.
        if "shell" in op_lower or ("exec" in op_lower and "exec_python" not in op_lower):
            violations.append("Artículo VI: Ejecución shell=True prohibida.")

        return {
            "operation": operation,
            "target": target,
            "allowed": len(violations) == 0,
            "violations": violations,
            "constitution_version": self._version,
        }


GLOBAL_CONSTITUTION = Constitution()
