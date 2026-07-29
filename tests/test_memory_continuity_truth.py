import sqlite3

from triade.memory.continuity_truth import enforce_memory_truth, memory_truth_snapshot


def test_false_ephemeral_claim_is_replaced(tmp_path):
    db = tmp_path / "triade.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE runs (id TEXT)")
        conn.execute("INSERT INTO runs VALUES ('run-1')")
        conn.execute("CREATE TABLE episodic_memory (id TEXT)")
    snapshot = memory_truth_snapshot(db)
    response, corrections = enforce_memory_truth(
        "¿Recuerdas fuera de cada sesión?",
        "No guardo nada; todo el contenido desaparecerá.",
        snapshot,
    )
    assert "conservo memoria persistente" in response
    assert "runs (1)" in response
    assert corrections == ["false_ephemeral_memory_claim_replaced"]


def test_truthful_answer_is_unchanged(tmp_path):
    db = tmp_path / "triade.db"
    db.touch()
    original = "Mi Bodega persiste entre sesiones y recupera contexto relevante."
    assert enforce_memory_truth(
        "¿Tienes memoria?", original, memory_truth_snapshot(db)
    ) == (original, [])


def test_vague_identity_answer_is_replaced_with_direct_continuity(tmp_path):
    db = tmp_path / "triade.db"
    db.touch()
    response, corrections = enforce_memory_truth(
        "¿Recuerdas fuera de cada sesión?",
        "Soy Tríade y tengo una Bodega.",
        memory_truth_snapshot(db),
    )
    assert response.startswith("Sí: conservo memoria persistente")
    assert corrections == ["memory_continuity_answer_enforced"]
