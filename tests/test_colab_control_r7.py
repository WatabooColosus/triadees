import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "tools" / "triade_colab_control_r7.py"
spec = importlib.util.spec_from_file_location("r7", MODULE)
r7 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r7)


def make_db(path, *, applications=15, activity=6, tasks=2500):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    for table in r7.GUARD_TABLES:
        con.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        limit = (
            applications
            if table == "neuron_education_applications"
            else tasks
            if table == "autonomous_tasks"
            else 1
        )
        con.executemany(
            f'INSERT INTO "{table}" (id) VALUES (?)',
            [(i,) for i in range(1, limit + 1)],
        )
    con.execute(
        "CREATE TABLE neuron_activity(id INTEGER PRIMARY KEY, activated INTEGER)"
    )
    con.executemany(
        "INSERT INTO neuron_activity(activated) VALUES (1)",
        [() for _ in range(activity)],
    )
    con.commit()
    con.close()


class FakeR5:
    def __init__(self, root):
        self.ROOT = root / "Triade"
        self.WORK = root / "work"
        self.BASE = root / "drive" / "Triade"
        self.DB = self.ROOT / "triade/memory/triade.db"
        self.WORK.mkdir(parents=True)
        self.BASE.mkdir(parents=True)
        self.DB.parent.mkdir(parents=True)
        (self.WORK / "restore_proof.json").write_text(
            json.dumps(
                {"owner_fingerprint": "verified_owner", "source_sha256": "a" * 64}
            )
        )

    def db_info(self, path):
        return {
            "status": "ok",
            "owner_fingerprint": "verified_owner",
            "counts": r7._counts(path),
        }

    def _owner_account_status(self, path):
        if not path.is_file():
            raise RuntimeError("no owner")
        return {"matches_owner_email": True}

    def check_working_identity(self):
        return {"integrity": "verified"}


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.r5 = FakeR5(self.root)
        make_db(self.r5.DB, applications=15, activity=6)
        proof_path = self.r5.WORK / "restore_proof.json"
        proof = json.loads(proof_path.read_text())
        proof["counts"] = r7._counts(self.r5.DB)
        proof_path.write_text(json.dumps(proof))
        self.center = r7.Center(self.r5)
        self.folder = (
            self.r5.BASE / "operacion_colab_r5" / "ramas_en_revision" / ("a" * 16)
        )
        self.folder.mkdir(parents=True)

    def checkpoint(
        self, *, apps=20, activity=7, tasks=2501, bad_hash=False, old_owner=False
    ):
        img = self.folder / "r5-test.sqlite3"
        make_db(img, applications=apps, activity=activity, tasks=tasks)
        info = {
            "status": "review_branch_only",
            "lineage": "90e9a51dd7ffef31",
            "file": img.name,
            "source_v2_sha256": "a" * 64,
            "code_sha": r7.PIN,
            "sha256": ("0" * 64 if bad_hash else r7._sha(img)),
            "counts": {
                k: v for k, v in r7._counts(img).items() if k != "neuron_activity"
            },
        }
        (self.folder / "latest_review.json").write_text(json.dumps(info))
        img.with_suffix(".json").write_text(json.dumps(info))
        return img

    def test_stale_v2_can_be_replaced_only_by_guarded_review(self):
        self.checkpoint()
        with patch.object(r7, "_check_api", return_value=False):
            out = self.center._restore_best_before_api()
        self.assertEqual(out["status"], "review_restored_validated")
        self.assertEqual(r7._counts(self.r5.DB)["neuron_education_applications"], 20)
        self.assertEqual(
            len(
                list(
                    (self.r5.WORK / "control_r7" / "before_review_restore").rglob(
                        "v2_pre_restore.sqlite3"
                    )
                )
            ),
            1,
        )
        self.assertEqual(r7._counts(self.r5.DB)["autonomous_tasks"], 2501)

    def test_activation_only_review_is_recovered(self):
        self.checkpoint(apps=15, activity=10, tasks=2500)
        with patch.object(r7, "_check_api", return_value=False):
            out = self.center._restore_best_before_api()
        self.assertEqual(out["status"], "review_restored_validated")
        self.assertEqual(r7._counts(self.r5.DB)["neuron_activity"], 10)

    def wal_connection(self, applications=16):
        conn = sqlite3.connect(self.r5.DB)
        self.addCleanup(conn.close)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.executemany(
            "INSERT INTO neuron_education_applications(id) VALUES (?)",
            [(i,) for i in range(16, applications + 1)],
        )
        conn.commit()
        return conn

    def test_restore_with_committed_wal_preserves_full_original(self):
        self.checkpoint()
        self.wal_connection()
        inode = self.r5.DB.stat().st_ino
        self.assertGreater(Path(str(self.r5.DB) + "-wal").stat().st_size, 0)
        with patch.object(r7, "_check_api", return_value=False):
            out = self.center._restore_best_before_api()
        self.assertEqual(out["restore_method"], "sqlite_backup_transaction")
        self.assertEqual(
            r7._counts(Path(out["backup_original"]))["neuron_education_applications"],
            16,
        )
        self.assertEqual(r7._counts(self.r5.DB)["neuron_education_applications"], 20)
        self.assertEqual(self.r5.DB.stat().st_ino, inode)

    def test_committed_wal_counts_cannot_be_replaced_by_older_review(self):
        self.checkpoint()
        self.wal_connection(applications=30)
        with (
            patch.object(r7, "_check_api", return_value=False),
            self.assertRaisesRegex(RuntimeError, "supera"),
        ):
            self.center._restore_best_before_api()
        self.assertEqual(r7._counts(self.r5.DB)["neuron_education_applications"], 30)

    def test_active_wal_writer_blocks_restore_without_losing_memory(self):
        self.checkpoint()
        conn = self.wal_connection()
        conn.execute("BEGIN IMMEDIATE")
        with (
            patch.object(r7, "_check_api", return_value=False),
            self.assertRaisesRegex(RuntimeError, "ocupada"),
        ):
            self.center._restore_best_before_api()
        conn.rollback()
        self.assertEqual(r7._counts(self.r5.DB)["neuron_education_applications"], 16)

    def test_unhealthy_api_listener_also_blocks_memory_restore(self):
        self.checkpoint()
        before = r7._sha(self.r5.DB)
        with (
            patch.object(r7, "_check_api", return_value=False),
            patch.object(r7, "_api_port_open", return_value=True),
            self.assertRaisesRegex(RuntimeError, "API activa"),
        ):
            self.center._restore_best_before_api()
        self.assertEqual(r7._sha(self.r5.DB), before)

    def test_interrupted_sqlite_backup_rolls_back_destination(self):
        image = self.checkpoint()
        with sqlite3.connect(image) as conn:
            conn.execute("CREATE TABLE backup_test_payload(data BLOB)")
            conn.executemany(
                "INSERT INTO backup_test_payload VALUES (zeroblob(8192))", [()] * 200
            )
        before = r7._counts(self.r5.DB)
        with (
            patch.object(r7.time, "monotonic", side_effect=[0, 61]),
            self.assertRaisesRegex(RuntimeError, "agotado"),
        ):
            r7._sqlite_backup(image, self.r5.DB)
        self.assertEqual(r7._counts(self.r5.DB), before)

    def test_stale_version_receipt_is_not_trusted(self):
        receipt = {
            "status": "rehydrated_candidate",
            "r631_source": "70e17c7e3f98b162cddf98a6441830e9802e3e55",
            "verified_module_sha256": "0" * 64,
        }
        self.assertFalse(self.center._release_verified(receipt))

    def test_hash_mismatch_no_changes(self):
        self.checkpoint(bad_hash=True)
        before = r7._sha(self.r5.DB)
        with (
            patch.object(r7, "_check_api", return_value=False),
            self.assertRaisesRegex(RuntimeError, "SHA"),
        ):
            self.center._restore_best_before_api()
        self.assertEqual(before, r7._sha(self.r5.DB))

    def test_prevent_old_review(self):
        self.checkpoint(apps=14, tasks=2400)
        before = r7._sha(self.r5.DB)
        with (
            patch.object(r7, "_check_api", return_value=False),
            self.assertRaisesRegex(RuntimeError, "supera"),
        ):
            self.center._restore_best_before_api()
        self.assertEqual(before, r7._sha(self.r5.DB))

    def test_no_review_if_v2_meets_floor(self):
        with patch.object(r7, "_check_api", return_value=False):
            x = self.center._restore_best_before_api()
        self.assertIn("no se reemplazó", x["result"])

    def test_warm_resume_checks_local_memory_without_reading_drive(self):
        baseline = r7._counts(self.r5.DB)
        with (
            patch.object(r7, "_check_api", return_value=True),
            patch.object(self.center, "_origin_verified", return_value=True),
            patch.object(self.center, "_release_verified", return_value=True),
            patch.object(
                self.center, "_floor", side_effect=AssertionError("Drive rehash")
            ),
            patch.object(
                self.center,
                "_checkpoint_index",
                side_effect=AssertionError("Drive scan"),
            ),
        ):
            self.assertTrue(self.center.resume_verified(baseline))
            with sqlite3.connect(self.r5.DB) as conn:
                conn.execute("DELETE FROM neuron_education_applications WHERE id=15")
            self.assertFalse(self.center.resume_verified(baseline))

    def test_warm_resume_requires_previously_verified_baseline(self):
        self.assertFalse(self.center.resume_verified(None))

    def test_cold_start_accepts_real_verified_zero_education(self):
        self.r5.DB.unlink()
        make_db(self.r5.DB, applications=0, activity=0)
        proof_path = self.r5.WORK / "restore_proof.json"
        proof = json.loads(proof_path.read_text())
        proof["counts"] = r7._counts(self.r5.DB)
        proof_path.write_text(json.dumps(proof))
        before = r7._sha(self.r5.DB)
        with patch.object(r7, "_check_api", return_value=False):
            result = self.center._restore_best_before_api()
        self.assertIn("no se reemplazó", result["result"])
        self.assertEqual(before, r7._sha(self.r5.DB))
        self.assertIsNone(self.center.status()["known_regression"])

    def test_discovers_verified_snapshot_without_latest_pointer(self):
        self.checkpoint()
        (self.folder / "latest_review.json").unlink()
        with patch.object(r7, "_check_api", return_value=False):
            result = self.center._restore_best_before_api()
        self.assertEqual(result["status"], "review_restored_validated")
        self.assertEqual(r7._counts(self.r5.DB)["neuron_education_applications"], 20)

    def test_does_not_restore_snapshot_that_loses_activated_rows(self):
        self.checkpoint(activity=0)
        before = r7._sha(self.r5.DB)
        with (
            patch.object(r7, "_check_api", return_value=False),
            self.assertRaisesRegex(RuntimeError, "supera"),
        ):
            self.center._restore_best_before_api()
        self.assertEqual(before, r7._sha(self.r5.DB))

    def test_packaged_rehydrator_uses_verified_baseline(self):
        from unittest.mock import Mock

        rehydrate = Mock(
            return_value={"status": "rehydrated_candidate", "api_http": 200}
        )
        center = r7.Center(self.r5, rehydrator=rehydrate)
        with (
            patch.object(center, "_origin_verified", return_value=True),
            patch.object(r7, "_check_api", return_value=True),
            patch.object(r7, "_git", side_effect=AssertionError("no legacy fetch")),
        ):
            self.assertEqual(center.install_release()["api_http"], 200)
        rehydrate.assert_called_once_with(
            self.r5, minimum_counts=r7._counts(self.r5.DB)
        )

    def test_rehydrator_accepts_zero_baseline_and_blocks_real_regression(self):
        from tools.triade_colab_continuity_r631 import verify_memory_floor

        self.r5.DB.unlink()
        make_db(self.r5.DB, applications=0, activity=0)
        proof_path = self.r5.WORK / "restore_proof.json"
        proof = json.loads(proof_path.read_text())
        proof["counts"] = r7._counts(self.r5.DB)
        proof_path.write_text(json.dumps(proof))
        observed = verify_memory_floor(self.r5, self.r5.DB.resolve())
        self.assertEqual(observed["neuron_education_applications"], 0)
        with self.assertRaisesRegex(RuntimeError, "retrocede"):
            verify_memory_floor(
                self.r5, self.r5.DB.resolve(), {"neuron_education_applications": 1}
            )

    def test_review_required_if_v2_regressed(self):
        self.r5.DB.unlink()
        make_db(self.r5.DB, applications=0, activity=1)
        with (
            patch.object(r7, "_check_api", return_value=False),
            self.assertRaisesRegex(RuntimeError, "retrocede"),
        ):
            self.center._restore_best_before_api()

    def test_no_live_db_swap(self):
        self.checkpoint()
        before = r7._sha(self.r5.DB)
        with (
            patch.object(r7, "_check_api", return_value=True),
            self.assertRaisesRegex(RuntimeError, "API activa"),
        ):
            self.center._restore_best_before_api()
        self.assertEqual(before, r7._sha(self.r5.DB))

    def test_review_pointer_belongs_to_source(self):
        self.checkpoint()
        p = self.folder / "latest_review.json"
        data = json.loads(p.read_text())
        data["source_v2_sha256"] = "b" * 64
        p.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError, "origen"):
            self.center._checkpoint_index()

    def test_start_existing_api_does_not_reinstall_r5(self):
        self.r5.start_guardian = lambda: {"status": "already_running"}
        with (
            patch.object(r7, "_check_api", return_value=True),
            patch.object(
                self.center,
                "install_release",
                return_value={"state": "already_installed"},
            ),
        ):
            out = self.center.start()
        self.assertEqual(out["state"], "already_running_verified")
        self.assertEqual(out["guardian"]["status"], "already_running")

    def test_start_blocked_on_missing_recovery_before_starting_api(self):
        self.r5.DB.unlink()
        make_db(self.r5.DB, applications=0, activity=1)
        self.r5.install_first = lambda: None
        self.r5.connect_verified_v2 = lambda: None
        self.r5.model_ready = lambda: self.fail(
            "model started despite regressed Bodega"
        )
        self.r5.start_real_backend = lambda: self.fail(
            "API started despite regressed Bodega"
        )
        with (
            patch.object(r7, "_check_api", return_value=False),
            self.assertRaisesRegex(RuntimeError, "retrocede"),
        ):
            self.center.start()

    def test_manifest_older_than_current_blocks(self):
        file = self.r5.BASE / "operacion_colab_r7" / "last_success.json"
        file.parent.mkdir(parents=True)
        file.write_text(
            json.dumps(
                {
                    "lineage": "90e9a51dd7ffef31",
                    "observed_counts": {"neuron_activity": 30},
                }
            )
        )
        with (
            patch.object(r7, "_check_api", return_value=False),
            self.assertRaisesRegex(RuntimeError, "retrocede"),
        ):
            self.center._restore_best_before_api()


if __name__ == "__main__":
    unittest.main()


def _seed_review_study(db, *, post_count):
    with sqlite3.connect(db) as conn:
        conn.execute("ALTER TABLE neuron_education_sessions ADD COLUMN session_id TEXT")
        conn.execute(
            "ALTER TABLE neuron_education_sessions ADD COLUMN neuron_id INTEGER"
        )
        conn.execute("ALTER TABLE neuron_education_sessions ADD COLUMN state TEXT")
        conn.execute(
            "UPDATE neuron_education_sessions SET "
            "session_id='education-proof',neuron_id=11,"
            "state=? WHERE id=1",
            ("applied_neutral" if post_count == 5 else "lesson_prepared",),
        )
        conn.execute(
            "CREATE TABLE neuron_functional_assessments "
            "(run_id TEXT, neuron_id INTEGER, phase TEXT)"
        )
        conn.executemany(
            "INSERT INTO neuron_functional_assessments VALUES (?,11,?)",
            [(f"pre{i}", "pre") for i in range(1, 6)]
            + [(f"post{i}", "post") for i in range(1, post_count + 1)],
        )


def _finished_study_pointer(r5):
    file = (
        r5.BASE
        / "operacion_colab_continua"
        / "aprendizaje"
        / ("a" * 16)
        / "current.json"
    )
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(
        json.dumps(
            {
                "phase": "done",
                "session_id": "education-proof",
                "neuron_id": 11,
                "pre": [{"run_id": f"pre{i}"} for i in range(1, 6)],
                "post": [{"run_id": f"post{i}"} for i in range(1, 6)],
                "result": {"session": {"state": "applied_neutral"}},
            }
        )
    )


def test_education_status_exposes_missing_real_evidence_without_mutation():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB)
        _seed_review_study(fake.DB, post_count=4)
        _finished_study_pointer(fake)
        before = r7._sha(fake.DB)
        center = r7.Center(fake)
        report = center.status()
        assert report["education_continuity"]["status"] == "regressed_blocked"
        assert "education-proof" in report["education_continuity"]["reason"]
        assert report["bodega"].startswith("SQLite ok")
        assert r7._sha(fake.DB) == before


def test_restore_blocks_count_dominant_checkpoint_that_lost_finished_run():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=15, tasks=2500)
        source = r7.Center(fake)
        folder = fake.BASE / "operacion_colab_r5" / "ramas_en_revision" / ("a" * 16)
        folder.mkdir(parents=True)
        image = folder / "r5-checkpoint.sqlite3"
        make_db(image, applications=20, tasks=2501)
        _seed_review_study(fake.DB, post_count=5)
        _seed_review_study(image, post_count=4)
        _finished_study_pointer(fake)
        manifest = {
            "status": "review_branch_only",
            "lineage": "90e9a51dd7ffef31",
            "file": image.name,
            "source_v2_sha256": "a" * 64,
            "code_sha": r7.PIN,
            "sha256": r7._sha(image),
            "counts": {
                k: v for k, v in r7._counts(image).items() if k != "neuron_activity"
            },
        }
        (folder / "latest_review.json").write_text(json.dumps(manifest))
        image.with_suffix(".json").write_text(json.dumps(manifest))
        before = r7._sha(fake.DB)
        with (
            patch.object(r7, "_check_api", return_value=False),
            unittest.TestCase().assertRaisesRegex(
                RuntimeError, "Continuidad educativa"
            ),
        ):
            source._restore_best_before_api()
        assert r7._sha(fake.DB) == before
        assert not (fake.WORK / "control_r7" / "before_review_restore").exists()


def test_restore_accepts_snapshot_with_verified_finished_run_ids():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=15, tasks=2500)
        center = r7.Center(fake)
        folder = fake.BASE / "operacion_colab_r5" / "ramas_en_revision" / ("a" * 16)
        folder.mkdir(parents=True)
        image = folder / "r5-checkpoint.sqlite3"
        make_db(image, applications=20, tasks=2501)
        _seed_review_study(fake.DB, post_count=4)
        _seed_review_study(image, post_count=5)
        _finished_study_pointer(fake)
        manifest = {
            "status": "review_branch_only",
            "lineage": "90e9a51dd7ffef31",
            "file": image.name,
            "source_v2_sha256": "a" * 64,
            "code_sha": r7.PIN,
            "sha256": r7._sha(image),
            "counts": {
                k: v for k, v in r7._counts(image).items() if k != "neuron_activity"
            },
        }
        (folder / "latest_review.json").write_text(json.dumps(manifest))
        image.with_suffix(".json").write_text(json.dumps(manifest))
        with patch.object(r7, "_check_api", return_value=False):
            restored = center._restore_best_before_api()
        assert restored["status"] == "review_restored_validated"
        assert r7._check_completed_study_evidence(fake.DB, fake.WORK, fake.BASE) == {
            "status": "finished_study_evidence_present",
            "runs": 10,
        }


def test_cannot_save_or_certify_review_from_restored_incomplete_study():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB)
        _seed_review_study(fake.DB, post_count=4)
        _finished_study_pointer(fake)
        center = r7.Center(fake)
        calls = []

        def save_review_copy():
            calls.append("saved")
            return {"status": "saved_review_only"}

        fake.save_review_copy = save_review_copy
        with unittest.TestCase().assertRaisesRegex(
            RuntimeError, "Continuidad educativa"
        ):
            center.save()
        with (
            patch.object(center, "_origin_verified", return_value=True),
            unittest.TestCase().assertRaisesRegex(
                RuntimeError, "Continuidad educativa"
            ),
        ):
            center.record_release()
        assert not calls
        assert not (fake.BASE / "operacion_colab_r7" / "last_success.json").exists()


def _review_fixture_for_isolated_fork(fake):
    image_root = fake.BASE / "operacion_colab_r5" / "ramas_en_revision" / ("a" * 16)
    image_root.mkdir(parents=True)
    image = image_root / "r5-checkpoint.sqlite3"
    make_db(image, applications=20, tasks=2501)
    _seed_review_study(image, post_count=4)
    _finished_study_pointer(fake)
    metadata = {
        "status": "review_branch_only",
        "lineage": "90e9a51dd7ffef31",
        "file": image.name,
        "source_v2_sha256": "a" * 64,
        "code_sha": r7.PIN,
        "sha256": r7._sha(image),
        "counts": {
            k: v for k, v in r7._counts(image).items() if k != "neuron_activity"
        },
    }
    (image_root / "latest_review.json").write_text(json.dumps(metadata))
    image.with_suffix(".json").write_text(json.dumps(metadata))
    return image


def test_prepares_only_local_isolated_fork_with_historical_evidence_quarantined():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=15)
        source = _review_fixture_for_isolated_fork(fake)
        live_sha = r7._sha(fake.DB)
        source_sha = r7._sha(source)
        drive_state = {
            str(path.relative_to(fake.BASE)): r7._sha(path)
            for path in fake.BASE.rglob("*")
            if path.is_file()
        }
        center = r7.Center(fake)
        fork = center.prepare_isolated_recovery()
        assert fork["status"] == "isolated_fork_prepared"
        assert fork["original_bodega_overwritten"] is False
        assert fork["drive_modified"] is False
        assert fork["api_started"] is False
        assert fork["workers_started"] is False
        assert fork["learning_authorized"] is False
        assert fork["study_promoted"] is False
        assert fork["recovery_certified"] is False
        assert fork["historical_study"]["run_refs_expected"] == 10
        assert fork["historical_study"]["run_refs_found"] == 9
        assert fork["historical_study"]["observed_state"] == "lesson_prepared"
        assert fork["historical_study"]["status"] == "quarantined_unverified"
        assert fork["historical_study"]["missing_refs"] == [
            {"run_id": "post5", "phase": "post"}
        ]
        copied = Path(fork["isolated_db"])
        assert copied.is_file()
        assert copied.is_relative_to(fake.WORK.resolve())
        assert not copied.is_relative_to(fake.BASE.resolve())
        assert r7._sha(copied) == source_sha
        assert r7._sha(fake.DB) == live_sha
        assert r7._sha(source) == source_sha
        assert drive_state == {
            str(path.relative_to(fake.BASE)): r7._sha(path)
            for path in fake.BASE.rglob("*")
            if path.is_file()
        }
        receipt = json.loads((copied.parent / "isolation_receipt.json").read_text())
        assert receipt["recovery_certified"] is False


def _unbacked_legacy_claim(r5):
    _finished_study_pointer(r5)
    folder = r5.BASE / "operacion_colab_continua" / "aprendizaje" / ("a" * 16)
    original = folder / "current.json"
    state = json.loads(original.read_text())
    state["rubric_version"] = "functional-probe-1"
    state["study_id"] = "prospective-real-legacy"
    state["backup"] = {"status": "encrypted_copy_verified"}
    original.write_text(json.dumps(state))
    return original


def test_uncertified_legacy_claim_quarantines_without_fabricating_probes():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=15, tasks=2500)
        original = _unbacked_legacy_claim(fake)
        before_pointer = original.read_bytes()
        folder = fake.BASE / "operacion_colab_r5" / "ramas_en_revision" / ("a" * 16)
        folder.mkdir(parents=True)
        image = folder / "r5-checkpoint.sqlite3"
        make_db(image, applications=20, tasks=2501)
        _seed_review_study(image, post_count=4)
        manifest = {
            "status": "review_branch_only",
            "lineage": "90e9a51dd7ffef31",
            "file": image.name,
            "source_v2_sha256": "a" * 64,
            "code_sha": r7.PIN,
            "sha256": r7._sha(image),
            "counts": {
                k: v for k, v in r7._counts(image).items() if k != "neuron_activity"
            },
        }
        (folder / "latest_review.json").write_text(json.dumps(manifest))
        image.with_suffix(".json").write_text(json.dumps(manifest))
        previous_v2 = r7._sha(fake.DB)
        with patch.object(r7, "_check_api", return_value=False):
            result = r7.Center(fake)._restore_best_before_api()
        assert result["status"] == "review_restored_quarantined_history"
        assert result["historical_education_certified"] is False
        assert (
            result["education_continuity"]["status"]
            == "historical_unverified_quarantined"
        )
        assert result["education_continuity"]["missing_evidence"] == [
            {"run_id": "post5", "phase": "post"}
        ]
        assert original.read_bytes() == before_pointer
        assert r7._sha(fake.DB) != previous_v2
        assert r7._counts(fake.DB)["neuron_education_applications"] == 20
        quarantine = original.parent / "quarantine" / r7._sha(original)
        assert (quarantine / "original.json").read_bytes() == before_pointer
        assert (quarantine / "receipt.json").is_file()
        with sqlite3.connect(fake.DB) as conn:
            assert conn.execute(
                "SELECT state FROM neuron_education_sessions "
                "WHERE session_id='education-proof'"
            ).fetchone() == ("lesson_prepared",)
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM neuron_functional_assessments"
                ).fetchone()[0]
                == 9
            )
        with unittest.TestCase().assertRaisesRegex(
            RuntimeError, "Continuidad educativa"
        ):
            r7._check_completed_study_evidence(fake.DB, fake.WORK, fake.BASE)


def test_certified_or_overwritten_legacy_claim_cannot_be_quarantined():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB)
        _seed_review_study(fake.DB, post_count=4)
        original = _unbacked_legacy_claim(fake)
        content = json.loads(original.read_text())
        content["backup"]["study_checkpoint"] = {"certified": True}
        original.write_text(json.dumps(content))
        assert (
            r7._legacy_quarantine_candidate(fake.DB, fake.WORK, fake.BASE, "f" * 64)
            is None
        )
        content["backup"].pop("study_checkpoint")
        content["phase"] = "checkpoint_pending"
        original.write_text(json.dumps(content))
        assert (
            r7._legacy_quarantine_candidate(fake.DB, fake.WORK, fake.BASE, "f" * 64)
            is None
        )


def test_quarantined_epoch_blocks_a_lost_new_probe():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB)
        _seed_review_study(fake.DB, post_count=4)
        original = _unbacked_legacy_claim(fake)
        receipt = r7._legacy_quarantine_candidate(
            fake.DB, fake.WORK, fake.BASE, "f" * 64
        )
        assert receipt is not None
        r7._persist_legacy_quarantine(fake.WORK, fake.BASE, receipt)
        epoch = original.parent / "epochs" / receipt["epoch"] / "current.json"
        epoch.parent.mkdir(parents=True)
        epoch.write_text(
            json.dumps(
                {
                    "phase": "post",
                    "neuron_id": 11,
                    "pre": [{"run_id": "pre1"}],
                    "post": [{"run_id": "new-post-not-committed"}],
                }
            )
        )
        with unittest.TestCase().assertRaisesRegex(RuntimeError, "retrocedida"):
            r7._verify_fresh_epoch(fake.DB, epoch)


def test_isolated_fork_refuses_to_write_when_work_is_inside_drive():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=15)
        _review_fixture_for_isolated_fork(fake)
        fake.WORK = fake.BASE / "work"
        fake.WORK.mkdir()
        center = r7.Center(fake)
        with unittest.TestCase().assertRaisesRegex(
            RuntimeError, "nunca se escribe en Drive"
        ):
            center.prepare_isolated_recovery()
        assert not (fake.WORK / "isolated_recovery").exists()


def _make_unbacked_single_pre_epoch(fake):
    review = _review_fixture_for_isolated_fork(fake)
    original = _unbacked_legacy_claim(fake)
    epoch_id = "recovery-" + r7._sha(original)[:16]
    epoch = original.parent / "epochs" / epoch_id / "current.json"
    epoch.parent.mkdir(parents=True, exist_ok=True)
    run_id = "run-20261105-164055-86c67953"
    state = {
        "phase": "pre",
        "rubric_version": "functional-probe-1",
        "neuron_id": 11,
        "study_id": "prospective-a-new-real-attempt",
        "pre": [
            {
                "run_id": run_id,
                "case_id": "vis1",
                "score": 0.0,
                "experimental_material_ids": [],
                "production_application_certified": False,
            }
        ],
        "post": [],
        "stable_promotion_authorized": False,
        "causal_improvement_certified": False,
    }
    epoch.write_text(json.dumps(state))
    return review, original, epoch, run_id


def test_orphaned_pre_run_is_archived_without_fabricating_or_rewriting_history():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=15, tasks=2500)
        review, original, epoch, run_id = _make_unbacked_single_pre_epoch(fake)
        original_bytes, epoch_bytes = original.read_bytes(), epoch.read_bytes()
        source_bytes = review.read_bytes()
        before = r7._sha(fake.DB)
        with patch.object(r7, "_check_api", return_value=False):
            result = r7.Center(fake)._restore_best_before_api()
        continuity = result["education_continuity"]
        assert result["status"] == "review_restored_quarantined_history"
        assert continuity["status"] == "historical_unverified_quarantined"
        assert continuity["historical_certified"] is False
        assert continuity["abandoned_pre_probe"] == {
            "status": "unbacked_archived",
            "missing_run_ids": [run_id],
        }
        assert continuity["new_study"] == {"status": "fresh_epoch_not_started"}
        assert continuity["new_epoch"].startswith("retry-")
        assert original.read_bytes() == original_bytes
        assert epoch.read_bytes() == epoch_bytes
        assert review.read_bytes() == source_bytes
        assert r7._sha(fake.DB) != before
        archived = epoch.parent / "abandoned" / r7._sha(epoch)
        assert (archived / "original.json").read_bytes() == epoch_bytes
        receipt = json.loads((archived / "receipt.json").read_text())
        assert receipt["historical_certified"] is False
        assert receipt["learning_credit"] is False
        assert receipt["selected_review_sha256"] == r7._sha(review)
        with sqlite3.connect(fake.DB) as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM neuron_functional_assessments WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
                == 0
            )
        # Retry the same running local image with no dominated review.
        with patch.object(r7, "_check_api", return_value=False):
            reused = r7.Center(fake)._restore_best_before_api()
        assert reused["result"] == "Bodega local intacta con cuarentena verificada"
        assert reused["education_continuity"]["new_epoch"] == continuity["new_epoch"]


def test_archived_pre_run_isolation_works_in_learning_namespace():
    from tools import triade_colab_learning as learning

    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=15, tasks=2500)
        _, original, old_epoch, _ = _make_unbacked_single_pre_epoch(fake)
        with patch.object(r7, "_check_api", return_value=False):
            r7.Center(fake)._restore_best_before_api()
        old_bytes = old_epoch.read_bytes()
        claim_bytes = original.read_bytes()
        epoch = learning._quarantined_epoch(fake)
        assert epoch is not None
        assert epoch["id"].startswith("retry-")
        assert epoch["remote"] != old_epoch
        assert learning._epoch_state(epoch) == {}
        assert learning._study_memory_lineage(fake)["status"] == (
            "quarantined_fresh_epoch_ready"
        )
        # Genuine later evidence may be written ONLY under an independent path.
        from types import SimpleNamespace

        def write(path, value):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))

        state = {
            "phase": "pre",
            "neuron_id": 11,
            "pre": [],
            "post": [],
            "study_id": "prospective-fresh-independent",
        }
        learning._save(
            {"r5": fake, "protection_module": SimpleNamespace(_json=write)}, state
        )
        assert epoch["remote"].is_file()
        assert old_epoch.read_bytes() == old_bytes
        assert original.read_bytes() == claim_bytes


def test_post_or_terminal_epoch_cannot_be_abandoned():
    for change in (
        {"phase": "post"},
        {"post": [{"run_id": "post-unbacked"}]},
        {"session_id": "education-existing"},
        {"backup": {"study_checkpoint": "verified"}},
    ):
        with tempfile.TemporaryDirectory() as root:
            fake = FakeR5(Path(root))
            make_db(fake.DB, applications=15, tasks=2500)
            _, original, epoch, _ = _make_unbacked_single_pre_epoch(fake)
            state = json.loads(epoch.read_text())
            state.update(change)
            epoch.write_text(json.dumps(state))
            live = r7._sha(fake.DB)
            with (
                patch.object(r7, "_check_api", return_value=False),
                unittest.TestCase().assertRaisesRegex(
                    RuntimeError, "Continuidad educativa"
                ),
            ):
                r7.Center(fake)._restore_best_before_api()
            assert r7._sha(fake.DB) == live
            assert not (epoch.parent / "abandoned").exists()
            assert original.is_file()


def test_conflicting_pre_epoch_mirrors_block_without_archiving():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=15, tasks=2500)
        _, _, epoch, _ = _make_unbacked_single_pre_epoch(fake)
        local = fake.WORK / ("prospective_" + epoch.parent.name + ".json")
        local.write_text(json.dumps({"phase": "pre", "pre": []}))
        before = r7._sha(fake.DB)
        with (
            patch.object(r7, "_check_api", return_value=False),
            unittest.TestCase().assertRaisesRegex(
                RuntimeError, "local/Drive divergente"
            ),
        ):
            r7.Center(fake)._restore_best_before_api()
        assert before == r7._sha(fake.DB)
        assert not (epoch.parent / "abandoned").exists()



def test_existing_local_probe_is_archived_as_real_sqlite_before_review_restore():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=15, tasks=2500)
        _, original, epoch, run_id = _make_unbacked_single_pre_epoch(fake)
        _seed_review_study(fake.DB, post_count=4)
        with sqlite3.connect(fake.DB) as conn:
            conn.execute(
                "INSERT INTO neuron_functional_assessments VALUES (?,11,'pre')",
                (run_id,),
            )
        original_sha, epoch_sha = r7._sha(original), r7._sha(epoch)
        with patch.object(r7, "_check_api", return_value=False):
            report = r7.Center(fake)._restore_best_before_api()
        receipt_root = epoch.parent / "abandoned" / epoch_sha
        receipt = json.loads((receipt_root / "receipt.json").read_text())
        assert receipt["local_run_present"] is True
        archived_db = receipt_root / "original-local.sqlite3"
        assert archived_db.is_file()
        assert r7._sha(archived_db) == receipt["source_local_sha256"]
        with sqlite3.connect(archived_db) as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM neuron_functional_assessments WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
                == 1
            )
        # The old real proof remains in an immutable Drive SQLite; it was not
        # reproduced or re-certified in the selected active review snapshot.
        with sqlite3.connect(fake.DB) as conn:
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM neuron_functional_assessments WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
                == 0
            )
        assert report["education_continuity"]["new_epoch"].startswith("retry-")
        assert r7._sha(original) == original_sha
        assert r7._sha(epoch) == epoch_sha


def test_missing_or_tampered_archived_local_sqlite_blocks_continuation():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=15, tasks=2500)
        _, _, epoch, run_id = _make_unbacked_single_pre_epoch(fake)
        _seed_review_study(fake.DB, post_count=4)
        with sqlite3.connect(fake.DB) as conn:
            conn.execute(
                "INSERT INTO neuron_functional_assessments VALUES (?,11,'pre')",
                (run_id,),
            )
        with patch.object(r7, "_check_api", return_value=False):
            r7.Center(fake)._restore_best_before_api()
        archived_db = (
            epoch.parent / "abandoned" / r7._sha(epoch) / "original-local.sqlite3"
        )
        archived_db.unlink()
        with unittest.TestCase().assertRaisesRegex(
            RuntimeError, "abandono de época no verificable"
        ):
            r7._quarantine_status(fake.DB, fake.WORK, fake.BASE)
