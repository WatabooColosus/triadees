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
