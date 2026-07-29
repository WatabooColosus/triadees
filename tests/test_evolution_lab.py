from __future__ import annotations

from dataclasses import replace

import pytest

from triade.evolution import EvolutionLab, EvolutionPolicy, Stage


DOMAINS = EvolutionPolicy().required_domains


def make_lab(tmp_path):
    return EvolutionLab(tmp_path / "evolution.db", signing_key=b"test-key")


def make_campaign(lab, policy=None):
    return lab.create_campaign("Mejora A", "A mejora generalización", "v1", "v2", policy)


def pass_measurement(lab, campaign_id):
    cases = [{"id": f"case-{i}", "domain": domain, "prompt": f"sealed-{i}"}
             for i, domain in enumerate(DOMAINS)]
    frozen = lab.freeze_battery(campaign_id, cases)
    assert frozen["sealed"] is True
    lab.record_evidence(
        campaign_id, Stage.MEASUREMENT, "baseline_comparison",
        {
            "baseline_overall": 0.75,
            "candidate_overall": 0.80,
            "candidate_scores": {domain: 0.80 for domain in DOMAINS},
            "regressions": {},
        },
        source="sealed-runner", independent=True,
    )
    assert lab.advance(campaign_id)["advanced"] is True


def test_battery_requires_all_domains_and_is_hash_only(tmp_path):
    lab = make_lab(tmp_path)
    campaign = make_campaign(lab)
    with pytest.raises(ValueError, match="faltan dominios"):
        lab.freeze_battery(campaign["campaign_id"], [{"domain": "reasoning"}])
    cases = [{"domain": d, "secret": f"answer-{i}"} for i, d in enumerate(DOMAINS)]
    result = lab.freeze_battery(campaign["campaign_id"], cases)
    assert result["case_count"] == len(DOMAINS)
    assert "answer" not in str(result)


def test_measurement_blocks_regression(tmp_path):
    lab = make_lab(tmp_path)
    cid = make_campaign(lab)["campaign_id"]
    lab.freeze_battery(cid, [{"domain": d, "input": d} for d in DOMAINS])
    lab.record_evidence(
        cid, Stage.MEASUREMENT, "baseline_comparison",
        {"baseline_overall": 0.8, "candidate_overall": 0.85,
         "candidate_scores": {d: 0.8 for d in DOMAINS}, "regressions": {"safety": -0.08}},
        source="runner", independent=True,
    )
    result = lab.advance(cid)
    assert result["advanced"] is False
    assert any("regresión" in reason for reason in result["decision"]["reasons"])


def test_full_six_stage_campaign_requires_evidence_and_is_signed(tmp_path):
    policy = replace(EvolutionPolicy(), minimum_independent_evidence=2)
    lab = make_lab(tmp_path)
    cid = make_campaign(lab, policy)["campaign_id"]
    pass_measurement(lab, cid)

    lesson = {"lesson": "hipótesis transferible", "hypothesis": "h1",
              "reproduction": {"seed": 7, "command": "safe-eval"},
              "transfer_contexts": ["context-a", "context-b", "context-c"]}
    lab.record_evidence(cid, Stage.EXPERIENCE, "reproducible_lesson", lesson,
                        source="evaluator-a", independent=True)
    lab.record_evidence(cid, Stage.EXPERIENCE, "replication", {**lesson, "replicated": True},
                        source="evaluator-b", independent=True)
    assert lab.advance(cid)["campaign"]["stage"] == Stage.ADAPTER

    adapter = tmp_path / "adapter.bin"
    adapter.write_bytes(b"signed adapter content")
    lab.register_artifact(cid, "adapter", adapter, parent_sha256="baseline-sha")
    for kind, payload in {
        "dataset_split": {"train_hash": "a", "validation_hash": "b", "test_hash": "c", "deduplicated": True},
        "adapter_training": {"method": "lora", "seed": 7, "completed": True},
        "ood_evaluation": {"score": 0.78},
        "forgetting_evaluation": {"regression": 0.01},
        "canary": {"observations": 5, "traffic_percent": 5, "rollback_ready": True},
    }.items():
        lab.record_evidence(cid, Stage.ADAPTER, kind, payload, source="adapter-lab", independent=kind != "adapter_training")
    lab.charge_resources(cid, gpu_minutes=20, experiments=1, storage_mb=50)
    assert lab.advance(cid)["campaign"]["stage"] == Stage.RESEARCH

    scientific_cycle = {
        "question": "¿Mejora la transferencia?",
        "sources": [{"url": "https://example.org/paper", "retrieved_at": "2026-07-28", "reputation": "peer_reviewed"}],
        "hypothesis": "sí bajo contextos nuevos", "prediction": "score > baseline",
        "experiment": {"protocol": "blind holdout", "seed": 7},
        "result": {"score": 0.81}, "refutation": {"attempted": True, "survived": True},
        "update": "mantener como candidato", "memory_status": "candidate",
    }
    lab.record_evidence(cid, Stage.RESEARCH, "scientific_cycle", scientific_cycle,
                        source="research-sandbox", independent=True)
    assert lab.advance(cid)["campaign"]["stage"] == Stage.LONG_HORIZON

    long_run = {
        "checkpoints": [{"id": 1}, {"id": 2}, {"id": 3}], "replans": 1,
        "stagnation_detection": True, "uncertainty_estimation": True,
        "recovered_after_restart": True,
    }
    lab.record_evidence(cid, Stage.LONG_HORIZON, "long_horizon_run", long_run,
                        source="prolonged-validator", independent=True)
    assert lab.advance(cid)["campaign"]["stage"] == Stage.EXTERNAL_EVALUATION

    for evaluator in ("external-a", "external-b"):
        lab.record_evidence(
            cid, Stage.EXTERNAL_EVALUATION, "external_report",
            {"evaluator": evaluator, "suite": "hidden-generalization", "score": 0.79,
             "report_hash": f"hash-{evaluator}", "signature": f"sig-{evaluator}"},
            source=evaluator, independent=True,
        )
    result = lab.advance(cid)
    assert result["advanced"] is True
    assert result["campaign"]["status"] == "validated"
    report = lab.report(cid)
    assert len(report["sha256"]) == 64
    assert len(report["signature"]) == 64


def test_research_cannot_write_stable_memory(tmp_path):
    lab = make_lab(tmp_path)
    cid = make_campaign(lab)["campaign_id"]
    pass_measurement(lab, cid)
    lesson = {"transfer_contexts": ["a", "b", "c"]}
    lab.record_evidence(cid, Stage.EXPERIENCE, "reproducible_lesson", lesson, source="a", independent=True)
    lab.record_evidence(cid, Stage.EXPERIENCE, "replication", lesson, source="b", independent=True)
    lab.advance(cid)
    artifact = tmp_path / "adapter.bin"; artifact.write_bytes(b"x")
    lab.register_artifact(cid, "adapter", artifact)
    for kind in ("dataset_split", "adapter_training", "ood_evaluation", "forgetting_evaluation"):
        lab.record_evidence(cid, Stage.ADAPTER, kind, {}, source="lab")
    lab.record_evidence(cid, Stage.ADAPTER, "canary", {"observations": 3, "rollback_ready": True}, source="lab")
    lab.advance(cid)
    payload = {k: True for k in ("question", "hypothesis", "prediction", "experiment", "result", "refutation", "update")}
    payload.update({"sources": [{"url": "https://example.org", "retrieved_at": "now"}], "memory_status": "stable"})
    lab.record_evidence(cid, Stage.RESEARCH, "scientific_cycle", payload, source="lab")
    decision = lab.evaluate_stage(cid)
    assert decision.passed is False
    assert any("memoria estable" in reason for reason in decision.reasons)


def test_resource_budget_blocks_long_horizon(tmp_path):
    policy = replace(EvolutionPolicy(), maximum_daily_experiments=1)
    lab = make_lab(tmp_path)
    cid = make_campaign(lab, policy)["campaign_id"]
    lab.charge_resources(cid, experiments=2)
    usage = lab.charge_resources(cid)
    assert usage["within_budget"] is False


def test_reject_marks_campaign_and_artifacts(tmp_path):
    lab = make_lab(tmp_path)
    cid = make_campaign(lab)["campaign_id"]
    artifact = tmp_path / "candidate.bin"; artifact.write_bytes(b"candidate")
    lab.register_artifact(cid, "adapter", artifact)
    campaign = lab.reject(cid, "regresión crítica")
    assert campaign["status"] == "rejected"
