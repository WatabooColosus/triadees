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


def test_status_reports_educational_regression_even_when_counts_have_no_regression():
    with tempfile.TemporaryDirectory() as root:
        fake = FakeR5(Path(root))
        make_db(fake.DB, applications=20, tasks=2500)
        _seed_review_study(fake.DB, post_count=4)
        _finished_study_pointer(fake)
        center = r7.Center(fake)
        with (
            patch.object(r7, "_check_api", return_value=False),
            patch.object(center, "_origin_verified", return_value=False),
        ):
            observed = center.status()
        assert observed["known_regression"] is None
        assert observed["education_continuity"]["status"] == "regressed_blocked"
        assert (
            "sesión concluida retrocedida" in observed["education_continuity"]["reason"]
        )
        assert observed["education_continuity"]["memory_modified"] is False
        assert observed["bodega"] == "SQLite ok / propietario validado"
