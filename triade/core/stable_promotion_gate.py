"""El único punto donde una firma humana es indispensable.

Regla de gobierno, y la razón de que este módulo exista separado:

    El humano no aprueba el aprendizaje. Aprueba que un aprendizaje demostrado
    pase a formar parte estable del organismo.

Investigar, cruzar fuentes, preparar currículos y lecciones, generar hipótesis,
crear candidatas, ejecutarlas en sandbox, medirlas, rechazarlas, ponerlas en
cuarentena, abrir canary, observarlo y revertir son acciones **reversibles o
aisladas**. Exigir una persona en cada una de ellas no aporta seguridad: solo
detiene el aprendizaje y convierte la aprobación en un trámite que se firma sin
mirar.

Promover a estable no es reversible en el mismo sentido: cambia lo que Tríade
*es* de forma duradera. Ahí, y solo ahí, hace falta alguien que decida.

Antes de esto el reparto estaba invertido en los dos extremos: proponer una
mejora exigía firma, y `_promote_experimental_to_stable` promovía en cuanto los
umbrales pasaban, sin pedirle permiso a nadie.
"""

from __future__ import annotations

import os
from typing import Any

#: Quién firma. Un nombre, no un booleano: una promoción estable debe poder
#: atribuirse a alguien concreto cuando se audite meses después.
STABLE_PROMOTION_APPROVER_ENV = "TRIADE_STABLE_PROMOTION_APPROVED_BY"

#: Escape hatch para entornos de prueba. Cuando se usa, la decisión queda
#: marcada como automática — nunca se disfraza de humana.
STABLE_PROMOTION_AUTO_ENV = "TRIADE_STABLE_PROMOTION_AUTO_APPROVE"

POLICY_APPROVER = "auto:stable_promotion_policy"


def stable_promotion_approval(neuron_name: str) -> dict[str, Any]:
    """¿Puede esta neurona pasar a estable ahora?

    Devuelve siempre quién decidió, incluso al denegar: si el aprobador solo
    apareciera en el camino feliz, una auditoría posterior no podría distinguir
    una promoción firmada de una automática.
    """
    approver = os.getenv(STABLE_PROMOTION_APPROVER_ENV, "").strip()
    if approver:
        return {
            "approved": True,
            "human": True,
            "approved_by": approver,
            "reason": "human_approved",
            "neuron": neuron_name,
        }
    if os.getenv(STABLE_PROMOTION_AUTO_ENV, "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return {
            "approved": True,
            "human": False,
            "approved_by": POLICY_APPROVER,
            "reason": "policy_auto_approved",
            "neuron": neuron_name,
        }
    return {
        "approved": False,
        "human": False,
        "approved_by": None,
        "reason": "human_approval_required",
        "neuron": neuron_name,
        "how_to_approve": (
            f"Exportar {STABLE_PROMOTION_APPROVER_ENV}=<nombre> tras revisar la "
            "evidencia del canary, o aprobar desde la Cabina Viva."
        ),
    }
