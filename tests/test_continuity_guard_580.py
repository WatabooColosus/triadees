"""Offline tests; no running Colab or Drive writes."""
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from continuity_guard_580 import ZIP_DB, compare


class ContinuityGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)

    def db(self, name, tasks):
        file = self.folder / name
        with sqlite3.connect(file) as db:
            db.execute('create table autonomous_tasks (task_id text primary key)')
            db.execute('create table neurons (name text primary key)')
            db.execute('create table neuron_education_sessions (session_id text primary key)')
            db.executemany('insert into autonomous_tasks values (?)', [(x,) for x in tasks])
            db.execute("insert into neurons values ('central')")
        return file

    def test_divergent_histories_blocked(self):
        old = self.db('old.db', ['a', 'b'])
        new = self.db('new.db', ['c'])
        result = compare(old, new)
        self.assertEqual(result['state'], 'BLOCK_RESTORE_OR_PROMOTION')
        self.assertEqual(result['tables']['autonomous_tasks']['shared'], 0)
        self.assertEqual(result['tables']['autonomous_tasks']['missing_from_candidate'], 2)

    def test_superset_ids_not_a_full_restore_claim(self):
        old = self.db('old.db', ['a'])
        new = self.db('new.db', ['a', 'b'])
        result = compare(old, new)
        self.assertEqual(result['state'], 'IDENTITIES_PRESERVED')
        self.assertFalse(result['certifies_full_restore'])

    def test_zip_backup(self):
        old = self.db('old.db', ['a'])
        candidate = self.db('candidate.db', [])
        file = self.folder / 'memory.zip'
        with zipfile.ZipFile(file, 'w') as z:
            z.write(old, ZIP_DB)
        result = compare(file, candidate)
        self.assertEqual(result['state'], 'BLOCK_RESTORE_OR_PROMOTION')
        self.assertEqual(result['reference']['source_type'], 'drive_memory_v2_zip')

    def test_source_never_mutated(self):
        old = self.db('old.db', ['a'])
        new = self.db('new.db', ['b'])
        import hashlib
        def hashfile(path):
            return hashlib.sha256(path.read_bytes()).hexdigest()
        before = (hashfile(old), hashfile(new))
        compare(old, new)
        self.assertEqual(before, (hashfile(old), hashfile(new)))


if __name__ == '__main__':
    unittest.main()
