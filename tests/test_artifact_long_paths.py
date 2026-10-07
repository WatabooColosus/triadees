import json

from triade.runtime.task_artifacts import AtomicArtifactWriter, CanonicalTaskArtifacts, _io_path


def test_atomic_evidence_writer_supports_long_paths(tmp_path):
    target = tmp_path / ("a" * 90) / ("b" * 90) / ("c" * 50) / "result.json"
    assert len(str(target)) > 260
    AtomicArtifactWriter.write_json(target, {"observed": "persisted"})
    assert json.loads(_io_path(target).read_text(encoding="utf-8")) == {"observed": "persisted"}
    assert len(CanonicalTaskArtifacts.sha256(target)) == 64
