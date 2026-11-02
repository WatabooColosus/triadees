import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "triade_colab_evidence_continuity.py"
)
spec = importlib.util.spec_from_file_location("evidence_continuity", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def fixture(tmp_path, status="failed"):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    drive = tmp_path / "drive"
    drive.mkdir()
    ref = "runs/background/20261102-worker/tasks/task-1/result.json"
    directory = runtime / Path(ref).parent
    directory.mkdir(parents=True)
    result = json.dumps({"error": "real_runtime_error"}).encode()
    input_data = b'{"task_type":"test"}'
    hashes = {
        "result.json": hashlib.sha256(result).hexdigest(),
        "input.json": hashlib.sha256(input_data).hexdigest(),
    }
    manifest = {
        "task_id": "task-1",
        "task_type": "test",
        "status": status,
        "worker_id": "worker-1",
        "lease_generation": 1,
        "result_hash": hashes["result.json"],
        "artifact_hashes": hashes,
    }
    (directory / "result.json").write_bytes(result)
    (directory / "input.json").write_bytes(input_data)
    (directory / "manifest.json").write_text(json.dumps(manifest))
    db = tmp_path / "db.sqlite3"
    with sqlite3.connect(db) as cx:
        cx.execute(
            "CREATE TABLE autonomous_tasks (task_id TEXT, task_type TEXT, status TEXT, worker_id TEXT, lease_generation INTEGER, result_ref TEXT, updated_at TEXT)"
        )
        cx.execute(
            "INSERT INTO autonomous_tasks VALUES (?,?,?,?,?,?,?)",
            ("task-1", "test", status, "worker-1", 1, ref, "2026-11-02T01:00:00Z"),
        )
    return runtime, drive, db, ref


def test_archive_restore_and_idempotence(tmp_path):
    rt, drive, db, ref = fixture(tmp_path)
    original_db = db.read_bytes()
    out = m.archive(db, rt, drive)
    assert out["archived"] == 1 and not out["memory_modified"]
    assert m.archive(db, rt, drive)["already_archived"] == 1
    folder = rt / Path(ref).parent
    import shutil

    shutil.rmtree(folder)
    restored = m.restore(rt, drive)
    assert restored["restored"] == 1
    assert (rt / ref).is_file() and db.read_bytes() == original_db
    assert m.restore(rt, drive)["already_present"] == 1


def test_tampered_manifest_refused(tmp_path):
    rt, drive, db, ref = fixture(tmp_path)
    (rt / ref).write_bytes(b'{"forged":true}')
    assert m.archive(db, rt, drive)["archived"] == 0


def test_root_cannot_escape_or_follow_symlink(tmp_path):
    rt, drive, db, ref = fixture(tmp_path)
    with sqlite3.connect(db) as cx:
        cx.execute("UPDATE autonomous_tasks SET result_ref=?", ("../out/result.json",))
    assert m.archive(db, rt, drive)["archived"] == 0
    with sqlite3.connect(db) as cx:
        cx.execute("UPDATE autonomous_tasks SET result_ref=?", (ref,))
    actual = rt / Path(ref).parent
    import shutil

    shutil.move(actual, tmp_path / "outside")
    actual.symlink_to(tmp_path / "outside", target_is_directory=True)
    assert m.archive(db, rt, drive)["archived"] == 0


def test_corruption_does_not_restore(tmp_path):
    rt, drive, db, ref = fixture(tmp_path)
    assert m.archive(db, rt, drive)["archived"] == 1
    import shutil

    shutil.rmtree(rt / Path(ref).parent)
    receipts = list((drive / "items").glob("*/*"))
    assert len(receipts) == 1
    (receipts[0] / "result.json").write_bytes(b"forged")
    o = m.restore(rt, drive)
    assert o["restored"] == 0 and o["invalid_receipts"] == 1 and not (rt / ref).exists()


def test_restore_wont_modify_conflicting_file(tmp_path):
    rt, drive, db, ref = fixture(tmp_path)
    assert m.archive(db, rt, drive)["archived"] == 1
    original = rt / ref
    original.write_bytes(b"changed")
    o = m.restore(rt, drive)
    assert o["conflicts"] == 1 and original.read_bytes() == b"changed"


def test_false_observation_missing_files_is_not_archived(tmp_path):
    rt, drive, db, ref = fixture(tmp_path)
    (rt / ref).unlink()
    o = m.archive(db, rt, drive)
    assert o["unavailable_or_invalid"] == 1 and o["archived"] == 0


def test_mismatched_sqlite_identity_refused(tmp_path):
    rt, drive, db, _ref = fixture(tmp_path)
    with sqlite3.connect(db) as cx:
        cx.execute("UPDATE autonomous_tasks SET status=?", ("completed",))
    assert m.archive(db, rt, drive)["archived"] == 0


def test_readonly_no_db_side_effects(tmp_path):
    rt, drive, db, _ref = fixture(tmp_path)
    with sqlite3.connect(db) as cx:
        cx.execute("PRAGMA journal_mode=DELETE")
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    assert m.archive(db, rt, drive)["archived"] == 1
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before
