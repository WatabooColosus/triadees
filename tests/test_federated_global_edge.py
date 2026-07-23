from triade.core.bodega_global_context import build_bodega_global_context
from triade.core.federated_global_edge import build_federated_global_edge_context
from triade.federation.federation import Federation


def test_federated_edge_is_global_sanitized_context(tmp_path):
    db = tmp_path / "triade.db"
    fed = Federation(db_path=db)
    fed.register_node("node-a", "Nodo A", trust_level="medium", permissions=["publish_capabilities"], capabilities={
        "online": True, "cpu_count": 4, "ram_available_gb": 6, "allowed_tasks": ["preprocess_text"], "secret": "never-expose",
    })
    result = build_federated_global_edge_context(db)
    assert result["nodes_total"] == 1
    assert result["nodes"][0]["provenance"] == "federation_registry:node-a"
    assert "secret" not in result["nodes"][0]["capabilities"]
    assert result["policy"]["node_input_is_evidence_not_truth"] is True


def test_bodega_global_contains_federated_edge(tmp_path):
    result = build_bodega_global_context("estado", db_path=tmp_path / "triade.db", runs_dir=tmp_path / "runs", semantic_recall_enabled=False)
    assert result["federated_global_edge_context"]["status"] == "ok"
