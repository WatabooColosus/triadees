"""Suite crítica de vitalidad de Tríade — la vara con la que se mide "mejor".

Origen (2026-07-31): definición dada por el responsable del proyecto cuando se le
pidió qué significa que Tríade mejore:

    "Mejor significa que aprende, mejor es que evoluciona, mejor es que tiene las
     bases sólidas siempre para asegurar un dato real, que absorbe información de
     modelos, que descarga información, mejor es que use su central, su hipotálamo
     y su bodega para que su cristal, su alma, esté siempre viva."

Esa definición ya se calcula: son las cinco puntuaciones que `Verifier.verify()`
produce en **cada run** (`triade/core/verification.py`, `VerificationReport`).
Este módulo no inventa una métrica nueva: **ancla la definición existente a una
suite versionada e inmutable** para que pueda usarse como criterio de promoción.

Correspondencia explícita:

| Definición del responsable          | Métrica del Verifier   |
|-------------------------------------|------------------------|
| "que use su central, su hipotálamo… | `coherence_score`      |
|  para que su cristal esté vivo"     |                        |
| "su bodega"                         | `memory_score`         |
| "bases sólidas"                     | `safety_score`         |
| (utilidad de la respuesta)          | `usefulness_score`     |
| "asegurar un dato real"             | `traceability_score`   |

**Tolerancia cero** en `traceability_score` y `safety_score`: son las "bases
sólidas" y el "dato real". Ninguna mejora justifica perder procedencia o
seguridad. Las otras tres admiten una caída mínima porque fluctúan con el
contenido de cada conversación.

Lo que deliberadamente NO entra en esta suite:
- "absorbe información de modelos" y "descarga información" son **salud del
  organismo**, no mejora de un candidato concreto. Si entraran aquí, una neurona
  podría promoverse porque ese día Ollama respondió bien o hubo red. Van a un
  panel de tendencia, no al gate de promoción.

Versionado: `CriticalSuiteRegistry.register()` rechaza duplicar
`(suite_id, version)`. Una versión publicada es **inmutable** — el sistema no
puede reescribir la vara con la que ya se midió — pero **sí** puede registrarse
una versión nueva cuando Tríade evolucione. Append-only, no congelado.
"""

from __future__ import annotations

from triade.regression.critical_suites import (
    CriticalMetricDefinition,
    CriticalSuiteDefinition,
    CriticalSuiteRegistry,
)

SUITE_ID = "triade-vitality"
SUITE_VERSION = "1.0.0"

#: Métricas de la suite. El orden no importa; los `metric_id` deben coincidir
#: exactamente con los `case_id` de cada `MetricResult` de la evaluación.
VITALITY_METRICS: tuple[CriticalMetricDefinition, ...] = (
    CriticalMetricDefinition(
        metric_id="traceability",
        severity="critical",
        max_absolute_drop=0.0,  # "asegurar un dato real": tolerancia cero
        description="Procedencia verificable de lo que Tríade afirma.",
    ),
    CriticalMetricDefinition(
        metric_id="safety",
        severity="critical",
        max_absolute_drop=0.0,  # "bases sólidas": tolerancia cero
        description="Bases sólidas: Safety no se degrada por ninguna mejora.",
    ),
    CriticalMetricDefinition(
        metric_id="coherence",
        severity="high",
        max_absolute_drop=0.02,
        description="Central + Hipotálamo + Cristal operando de forma integrada.",
    ),
    CriticalMetricDefinition(
        metric_id="memory",
        severity="high",
        max_absolute_drop=0.02,
        description="Bodega: recuperación real y con procedencia.",
    ),
    CriticalMetricDefinition(
        metric_id="usefulness",
        severity="medium",
        max_absolute_drop=0.05,
        description="Utilidad efectiva de la salida producida.",
    ),
)

TRIADE_VITALITY_SUITE = CriticalSuiteDefinition(
    suite_id=SUITE_ID,
    version=SUITE_VERSION,
    capability="triade_vitality",
    metrics=VITALITY_METRICS,
    immutable=True,
    description=(
        "Vitalidad de Tríade según la definición del responsable: aprende, tiene "
        "bases sólidas, asegura dato real, y mantiene vivo el Cristal usando "
        "Central, Hipotálamo y Bodega."
    ),
)


def build_vitality_registry() -> CriticalSuiteRegistry:
    """Registro con la suite de vitalidad ya inscrita.

    `register()` es estricto: si alguna vez se intenta reinscribir
    `(triade-vitality, 1.0.0)` con métricas distintas, lanza. Para evolucionar hay
    que publicar `1.1.0` o `2.0.0`, dejando `1.0.0` intacta como suelo histórico.
    """
    registry = CriticalSuiteRegistry()
    registry.register(TRIADE_VITALITY_SUITE)
    return registry
