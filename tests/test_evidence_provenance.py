from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from triade.runtime.evidence_provenance import EvidenceProvenanceStore, EvidenceRecord


def test_autonomous_event_is_not_external_evidence(tmp_path: Path) -> None:
    evidence = EvidenceProvenanceStore(tmp_path / "db.sqlite").create(
        origin_class="autonomous", producer_id="worker", source="pulse", content="x"
    )
    assert not evidence.independently_external
    assert evidence.root_external_event_id is None


def test_derived_evidence_preserves_external_root(tmp_path: Path) -> None:
    store = EvidenceProvenanceStore(tmp_path / "db.sqlite")
    root = store.create(
        origin_class="external_system", producer_id="api", source="https://source", content="x"
    )
    derived = store.create(
        origin_class="derived", producer_id="worker", source="summary", content="y",
        causal_parent_id=root.evidence_id,
    )
    assert derived.root_external_event_id == root.evidence_id
    assert derived.autonomous_depth == 1


def test_same_evidence_is_not_consumed_twice(tmp_path: Path) -> None:
    store = EvidenceProvenanceStore(tmp_path / "db.sqlite")
    item = store.create(
        origin_class="human", producer_id="user", source="chat", content="correction"
    )
    assert store.consume(item.evidence_id, consumer_type="neuron", consumer_id="critic")
    assert not store.consume(item.evidence_id, consumer_type="neuron", consumer_id="critic")


def test_unknown_origin_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate({
            "evidence_id": "x", "origin_class": "pretend_external", "producer_id": "x",
            "source": "x", "content_hash": "x", "created_at": datetime.now(UTC).isoformat(),
            "trust_level": "x", "verification_status": "x",
        })


def test_autonomous_depth_limit_blocks_recursion(tmp_path: Path) -> None:
    store = EvidenceProvenanceStore(tmp_path / "db.sqlite", max_autonomous_depth=2)
    root = store.create(
        origin_class="human", producer_id="u", source="chat", content="x"
    )
    one = store.create(
        origin_class="derived", producer_id="w", source="one", content="1",
        causal_parent_id=root.evidence_id,
    )
    two = store.create(
        origin_class="derived", producer_id="w", source="two", content="2",
        causal_parent_id=one.evidence_id,
    )
    with pytest.raises(ValueError, match="autonomous_depth_limit"):
        store.create(
            origin_class="derived", producer_id="w", source="three", content="3",
            causal_parent_id=two.evidence_id,
        )


def test_external_evidence_after_last_cycle_can_wake_neuron(tmp_path: Path) -> None:
    store = EvidenceProvenanceStore(tmp_path / "db.sqlite")
    now = datetime.now(UTC)
    item = store.create(
        origin_class="external_system", producer_id="api", source="event", content="x",
        created_at=now.isoformat(),
    )
    assert store.can_wake_neuron(
        item.evidence_id, last_cycle_at=(now - timedelta(seconds=1)).isoformat()
    )


def test_old_evidence_cannot_wake_neuron(tmp_path: Path) -> None:
    store = EvidenceProvenanceStore(tmp_path / "db.sqlite")
    old = datetime.now(UTC) - timedelta(days=1)
    item = store.create(
        origin_class="external_system", producer_id="api", source="event", content="x",
        created_at=old.isoformat(),
    )
    assert not store.can_wake_neuron(
        item.evidence_id, last_cycle_at=datetime.now(UTC).isoformat()
    )
