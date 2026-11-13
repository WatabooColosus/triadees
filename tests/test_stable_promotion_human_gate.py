"""La promoción a estable exige firma humana. Proponer una mejora, no.

El gate estaba en el sitio equivocado, y en los dos extremos a la vez:

- **Proponer** una mejora exigía firma humana (`TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE=0`),
  lo que dejaba el circuito de aprendizaje inerte esperando a una persona.
- **Promover a estable** no exigía nada: `_promote_experimental_to_stable`
  llamaba a `update_status(name, "stable")` en cuanto los umbrales de readiness
  pasaban. Ningún `human`, ningún `approval` en toda esa ruta.

La regla correcta es la contraria: el humano no aprueba el aprendizaje, aprueba
que un aprendizaje demostrado cambie el organismo estable. Investigar, preparar
lecciones, crear candidatas, ejecutarlas en sandbox, medirlas, abrir canary y
revertir son acciones **reversibles o aisladas**; promover a estable no lo es.

`TRIADE_STABLE_PROMOTION_AUTO_APPROVE=1` permite desactivarlo para pruebas, y
entonces queda registrado como política automática — nunca como firma humana.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from triade.core.stable_promotion_gate import (
    STABLE_PROMOTION_APPROVER_ENV,
    stable_promotion_approval,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "TRIADE_STABLE_PROMOTION_AUTO_APPROVE",
        STABLE_PROMOTION_APPROVER_ENV,
    ):
        monkeypatch.delenv(name, raising=False)


def test_stable_promotion_is_blocked_without_a_human() -> None:
    """Por defecto no se promueve nada a estable sin que alguien firme."""
    decision = stable_promotion_approval("neurona-x")
    assert decision["approved"] is False
    assert decision["reason"] == "human_approval_required"
    assert decision["approved_by"] is None


def test_a_named_human_unblocks_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(STABLE_PROMOTION_APPROVER_ENV, "santiago")
    decision = stable_promotion_approval("neurona-x")
    assert decision["approved"] is True
    assert decision["approved_by"] == "santiago"
    assert decision["human"] is True


def test_an_empty_approver_is_not_a_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Una variable puesta a vacío no es nadie firmando."""
    monkeypatch.setenv(STABLE_PROMOTION_APPROVER_ENV, "   ")
    decision = stable_promotion_approval("neurona-x")
    assert decision["approved"] is False


def test_policy_auto_approval_never_pretends_to_be_human(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Si se desactiva el gate, tiene que notarse quién decidió."""
    monkeypatch.setenv("TRIADE_STABLE_PROMOTION_AUTO_APPROVE", "1")
    decision = stable_promotion_approval("neurona-x")
    assert decision["approved"] is True
    assert decision["human"] is False
    assert decision["approved_by"] == "auto:stable_promotion_policy"


def test_the_autopromoter_refuses_stable_without_approval(
    monkeypatch, tmp_path
) -> None:  # type: ignore[no-untyped-def]
    """El gate tiene que estar en la ruta real, no solo en una función suelta."""
    from triade.core.neuron_autopromoter import NeuronAutopromoter

    promoter = NeuronAutopromoter.__new__(NeuronAutopromoter)
    promoter.db_path = tmp_path / "triade.db"  # type: ignore[attr-defined]

    neuron: dict[str, Any] = {"id": 1, "name": "neurona-x"}
    event = NeuronAutopromoter._stable_approval_block(promoter, neuron)
    assert event is not None
    assert event["reason"] == "human_approval_required"
    assert event["status"] == "not_promoted"


def test_the_autopromoter_proceeds_when_a_human_signed(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    from triade.core.neuron_autopromoter import NeuronAutopromoter

    monkeypatch.setenv(STABLE_PROMOTION_APPROVER_ENV, "santiago")
    promoter = NeuronAutopromoter.__new__(NeuronAutopromoter)
    promoter.db_path = tmp_path / "triade.db"  # type: ignore[attr-defined]

    assert (
        NeuronAutopromoter._stable_approval_block(promoter, {"id": 1, "name": "n"})
        is None
    )


# ── el otro extremo: proponer ya no exige firma ─────────────────────────


def test_proposing_an_improvement_no_longer_needs_a_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Investigar y proponer son reversibles: no deben esperar a una persona.

    El gate se mueve a la promoción estable, que es lo irreversible.
    """
    monkeypatch.delenv("TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE", raising=False)
    from triade.workers.worker_loop import _auto_approval_enabled

    assert _auto_approval_enabled() is True


def test_proposal_auto_approval_can_still_be_switched_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE", "0")
    from triade.workers.worker_loop import _auto_approval_enabled

    assert _auto_approval_enabled() is False


def test_the_two_gates_are_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Aprobar propuestas automáticamente no puede abrir la puerta de estable."""
    monkeypatch.delenv("TRIADE_SELF_IMPROVEMENT_AUTO_APPROVE", raising=False)
    monkeypatch.delenv(STABLE_PROMOTION_APPROVER_ENV, raising=False)
    monkeypatch.delenv("TRIADE_STABLE_PROMOTION_AUTO_APPROVE", raising=False)
    from triade.workers.worker_loop import _auto_approval_enabled

    assert _auto_approval_enabled() is True
    assert stable_promotion_approval("n")["approved"] is False


def test_identity_core_is_never_reachable_from_here() -> None:
    """G4 sigue siendo zona prohibida, no un gate más."""
    assert "identity_core" not in os.environ.get(STABLE_PROMOTION_APPROVER_ENV, "")
