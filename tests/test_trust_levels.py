"""Tests para TrustLevelStore y auto-consolidación (Fase F-05)."""
from __future__ import annotations

import math
import sqlite3
from pathlib import Path

import pytest

from triade.learning.pipeline import LearningPipeline
from triade.memory.trust_store import (
    PERMISSION_THRESHOLDS,
    TRUST_DOMAINS,
    TrustLevelStore,
)


# ── helpers ─────────────────────────────────────────────────────────────────


def trust_store(tmp_path: Path) -> TrustLevelStore:
    return TrustLevelStore(db_path=tmp_path / "triade.db")


def insert_run(conn: sqlite3.Connection, run_id: str = "run-t-1") -> None:
    conn.execute(
        """INSERT OR IGNORE INTO runs
        (run_id, source, user_input, status, model_hypothalamus, model_central, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (run_id, "test", "test input", "ok", "rules", "template", "2026-06-10"),
    )


def insert_reward(conn: sqlite3.Connection, reward: float, run_id: str = "run-t-1") -> None:
    insert_run(conn, run_id)
    conn.execute(
        "INSERT INTO reinforcement_log (run_id, reward, hypothalamus_quality, central_quality, coherence_score) VALUES (?, ?, ?, ?, ?)",
        (run_id, reward, 0.5, 0.5, 0.8),
    )


def insert_verification(
    conn: sqlite3.Connection, status: str, run_id: str = "run-t-1"
) -> None:
    insert_run(conn, run_id)
    conn.execute(
        "INSERT INTO verification_reports (run_id, status) VALUES (?, ?)",
        (run_id, status),
    )


def insert_model_event(conn: sqlite3.Connection, ok: int, run_id: str = "run-t-1") -> None:
    insert_run(conn, run_id)
    conn.execute(
        "INSERT INTO model_events (run_id, role, provider, model_name, ok) VALUES (?, ?, ?, ?, ?)",
        (run_id, "hypothalamus", "test", "test-model", ok),
    )


def pipeline(tmp_path: Path) -> LearningPipeline:
    return LearningPipeline(db_path=tmp_path / "triade.db")


def good_candidate(pipe: LearningPipeline) -> str:
    return pipe.ingest(
        content="Procedimiento verificado para preparar cold brew.",
        source_type="document",
        source_ref="manual-coldbrew-v2",
        title="Cold brew",
        domain="cafe",
        risk_level="low",
    )["candidate_id"]


# ── TrustLevelStore unit tests ──────────────────────────────────────────────


class TestTrustLevelStore:
    def test_init_creates_schema(self, tmp_path: Path) -> None:
        store = trust_store(tmp_path)
        assert store.db_path.exists()
        with store._connect() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        names = {r["name"] for r in tables}
        assert "trust_levels" in names

    def test_get_trust_returns_zero_by_default(self, tmp_path: Path) -> None:
        store = trust_store(tmp_path)
        for domain in TRUST_DOMAINS:
            assert store.get_trust(domain) == 0.0

    def test_get_trust_unknown_domain_returns_zero(self, tmp_path: Path) -> None:
        store = trust_store(tmp_path)
        assert store.get_trust("nonexistent") == 0.0

    def test_get_permissions_all_false_at_zero_trust(self, tmp_path: Path) -> None:
        store = trust_store(tmp_path)
        for domain in TRUST_DOMAINS:
            perms = store.get_permissions(domain)
            for perm, thr in PERMISSION_THRESHOLDS[domain].items():
                assert perms[perm] is False, f"Expected False for {perm} at trust 0.0"

    def test_recompute_all_with_no_data_returns_zero(self, tmp_path: Path) -> None:
        store = trust_store(tmp_path)
        levels = store.recompute_all()
        for d in TRUST_DOMAINS:
            assert levels[d] == 0.0

    def test_recompute_all_with_good_data_increases_trust(self, tmp_path: Path) -> None:
        store = trust_store(tmp_path)
        with store._connect() as conn:
            for i in range(10):
                rid = f"run-g-{i}"
                insert_reward(conn, 0.9, rid)
                insert_verification(conn, "ok", rid)
                insert_model_event(conn, 1, rid)

        levels = store.recompute_all()
        for d in TRUST_DOMAINS:
            assert levels[d] > 0.0, f"{d} should have non-zero trust"
            assert 0.0 <= levels[d] <= 1.0

    def test_recompute_all_persists_values(self, tmp_path: Path) -> None:
        store = trust_store(tmp_path)
        with store._connect() as conn:
            for i in range(5):
                rid = f"run-p-{i}"
                insert_reward(conn, 0.8, rid)
                insert_verification(conn, "ok", rid)

        before = store.recompute_all()
        # new store reading same db
        store2 = trust_store(tmp_path)
        for d in TRUST_DOMAINS:
            assert math.isclose(store2.get_trust(d), before[d], rel_tol=1e-4)

    def test_recompute_all_with_bad_data_keeps_trust_low(self, tmp_path: Path) -> None:
        store = trust_store(tmp_path)
        with store._connect() as conn:
            for i in range(10):
                rid = f"run-b-{i}"
                insert_reward(conn, 0.1, rid)
                insert_verification(conn, "fail", rid)
                insert_model_event(conn, 0, rid)

        levels = store.recompute_all()
        for d in TRUST_DOMAINS:
            assert levels[d] < 0.5, f"{d} should be low with bad data: {levels[d]}"

    def test_doctor_returns_structured_report(self, tmp_path: Path) -> None:
        store = trust_store(tmp_path)
        with store._connect() as conn:
            for i in range(3):
                rid = f"run-d-{i}"
                insert_reward(conn, 0.7, rid)
                insert_verification(conn, "ok", rid)

        store.recompute_all()
        report = store.doctor()
        assert report["status"] == "ok"
        assert set(report["domains"].keys()) == set(TRUST_DOMAINS)
        for d in TRUST_DOMAINS:
            assert "trust_level" in report["domains"][d]
            assert "criteria" in report["domains"][d]
            assert "permissions" in report["domains"][d]


# ── Integration: auto-consolidation ─────────────────────────────────────────


class TestAutoConsolidation:
    def test_auto_consolidate_low_risk_fails_when_trust_zero(self, tmp_path: Path) -> None:
        pipe = pipeline(tmp_path)
        cid = good_candidate(pipe)
        pipe.evaluate(cid)
        pipe.verify(cid)

        with pytest.raises(ValueError, match="Trust insuficiente|auto-consolidar|run_uses"):
            pipe.consolidate(cid, auto_consolidate=True)

    def test_auto_consolidate_low_risk_succeeds_when_trust_above_threshold(
        self, tmp_path: Path
    ) -> None:
        pipe = pipeline(tmp_path)
        store = TrustLevelStore(db_path=pipe.db_path)
        with store._connect() as conn:
            for i in range(20):
                rid = f"run-a-{i}"
                insert_reward(conn, 0.9, rid)
                insert_verification(conn, "ok", rid)
                insert_model_event(conn, 1, rid)
        store.recompute_all()
        assert store.get_trust("consolidation") >= 0.25, "trust should be >= 0.25"

        cid = good_candidate(pipe)
        pipe.evaluate(cid)
        pipe.verify(cid)
        for i in range(5):
            pipe.mark_used_in_run(cid, f"run-trust-{i}", outcome_score=0.85)

        result = pipe.consolidate(cid, auto_consolidate=True)
        assert result["status"] == "consolidated"
        notes = result["verification_notes"]["consolidated"]
        assert notes["auto_consolidated"] is True
        assert notes["approved_by"] == "trust-system@low"

    def test_auto_consolidate_medium_risk_succeeds_with_high_trust(
        self, tmp_path: Path
    ) -> None:
        pipe = pipeline(tmp_path)
        store = TrustLevelStore(db_path=pipe.db_path)
        with store._connect() as conn:
            for i in range(100):
                rid = f"run-m-{i}"
                insert_reward(conn, 0.95, rid)
                insert_verification(conn, "ok", rid)
                insert_model_event(conn, 1, rid)
        store.recompute_all()
        assert store.get_trust("consolidation") >= 0.50, "trust should be >= 0.50"

        cid = pipe.ingest(
            content="Procedimiento de mediana complejidad.",
            source_type="document",
            source_ref="medium-ref",
            title="Medium",
            domain="general",
            risk_level="medium",
        )["candidate_id"]
        pipe.evaluate(cid)
        pipe.verify(cid)
        for i in range(5):
            pipe.mark_used_in_run(cid, f"run-medium-{i}", outcome_score=0.80)

        result = pipe.consolidate(cid, auto_consolidate=True)
        assert result["status"] == "consolidated"
        notes = result["verification_notes"]["consolidated"]
        assert notes["approved_by"] == "trust-system@medium"

    def test_auto_consolidate_high_risk_succeeds_with_very_high_trust(
        self, tmp_path: Path
    ) -> None:
        pipe = pipeline(tmp_path)
        store = TrustLevelStore(db_path=pipe.db_path)
        with store._connect() as conn:
            for i in range(500):
                rid = f"run-h-{i}"
                insert_reward(conn, 1.0, rid)
                insert_verification(conn, "ok", rid)
                insert_model_event(conn, 1, rid)
        store.recompute_all()
        assert store.get_trust("consolidation") >= 0.80, "trust should be >= 0.80"

        cid = pipe.ingest(
            content="Procedimiento de alta complejidad.",
            source_type="document",
            source_ref="high-ref",
            title="High",
            domain="general",
            risk_level="high",
        )["candidate_id"]
        pipe.evaluate(cid)
        pipe.verify(cid)
        for i in range(5):
            pipe.mark_used_in_run(cid, f"run-high-{i}", outcome_score=0.90)

        result = pipe.consolidate(cid, auto_consolidate=True)
        assert result["status"] == "consolidated"
        notes = result["verification_notes"]["consolidated"]
        assert notes["approved_by"] == "trust-system@high"

    def test_auto_consolidate_critical_risk_still_blocked(self, tmp_path: Path) -> None:
        pipe = pipeline(tmp_path)
        store = TrustLevelStore(db_path=pipe.db_path)
        with store._connect() as conn:
            for i in range(500):
                rid = f"run-cr-{i}"
                insert_reward(conn, 1.0, rid)
                insert_verification(conn, "ok", rid)
                insert_model_event(conn, 1, rid)
        store.recompute_all()

        cid = pipe.ingest(
            content="Acción crítica.",
            source_type="document",
            source_ref="crit-ref",
            domain="infra",
            risk_level="critical",
        )["candidate_id"]
        pipe.evaluate(cid)
        # critical risk se rechaza en verify, nunca llega a consolidated
        result = pipe.verify(cid)
        assert result["status"] == "rejected"

        with pytest.raises((ValueError, KeyError)):
            pipe.consolidate(cid, auto_consolidate=True)

    def test_auto_consolidate_does_not_affect_human_approval_path(
        self, tmp_path: Path
    ) -> None:
        pipe = pipeline(tmp_path)
        cid = good_candidate(pipe)
        pipe.evaluate(cid)
        pipe.verify(cid)
        for i in range(5):
            pipe.mark_used_in_run(cid, f"run-human-{i}", outcome_score=0.85)

        result = pipe.consolidate(cid, approved_by="santiago")
        assert result["status"] == "consolidated"
        notes = result["verification_notes"]["consolidated"]
        assert notes["auto_consolidated"] is False
        assert notes["approved_by"] == "santiago"

    def test_auto_consolidate_requires_verified_status(self, tmp_path: Path) -> None:
        pipe = pipeline(tmp_path)
        cid = good_candidate(pipe)

        with pytest.raises(ValueError, match="verified"):
            pipe.consolidate(cid, auto_consolidate=True)

    def test_pipeline_doctor_includes_trust_info(self, tmp_path: Path) -> None:
        pipe = pipeline(tmp_path)
        doctor = pipe.doctor()
        assert "trust_system" in doctor["policy"]
        assert "consolidation_trust" in doctor["policy"]["trust_system"]
        assert "permissions" in doctor["policy"]["trust_system"]
