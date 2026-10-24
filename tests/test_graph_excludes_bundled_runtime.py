from triade.observability.code_graph import iter_python_files
from triade.observability.file_graph import build_file_graph


def test_bundled_interpreter_is_not_cognitive_architecture(tmp_path):
    (tmp_path / "tools/python/Lib").mkdir(parents=True)
    (tmp_path / "tools/python/Lib/stdlib.py").write_text("pass")
    (tmp_path / "tools/operator.py").write_text("pass")
    assert list(iter_python_files(tmp_path)) == [tmp_path / "tools/operator.py"]
    nodes, _ = build_file_graph(tmp_path)
    assert not any("stdlib" in n.node_id for n in nodes)
    assert any("operator.py" in n.node_id for n in nodes)


def test_file_hashing_does_not_load_whole_artifacts(tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path

    payload = b"runtime evidence"
    (tmp_path / "evidence.bin").write_bytes(payload)

    def forbidden_full_read(self):
        raise AssertionError("whole-file reads violate bounded-memory hashing")

    monkeypatch.setattr(Path, "read_bytes", forbidden_full_read)
    nodes, _ = build_file_graph(tmp_path)
    node = next(n for n in nodes if n.label == "evidence.bin")
    assert node.metadata["sha256"] == hashlib.sha256(payload).hexdigest()
