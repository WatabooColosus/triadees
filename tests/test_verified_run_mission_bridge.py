import sqlite3
from pathlib import Path
import tempfile
import unittest
from verified_run_mission_bridge import bridge_verified_user_run

CREATE = '''
CREATE TABLE neurons (id INTEGER PRIMARY KEY);
CREATE TABLE runs (run_id TEXT PRIMARY KEY, source TEXT);
CREATE TABLE verification_reports (id INTEGER PRIMARY KEY, run_id TEXT, status TEXT, coherence_score REAL, memory_score REAL, safety_score REAL, usefulness_score REAL, traceability_score REAL);
CREATE TABLE neuron_activity (id INTEGER PRIMARY KEY, run_id TEXT, neuron_id INTEGER, activated INTEGER);
CREATE TABLE neuron_missions (id INTEGER PRIMARY KEY, neuron_id INTEGER, status TEXT);
CREATE TABLE neuron_evidence (id INTEGER PRIMARY KEY, mission_id INTEGER, neuron_id INTEGER, evidence_type TEXT, source TEXT, content TEXT, refs_json TEXT, score REAL, created_at TEXT);
'''

class Cases(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name)/'test.sqlite3'
        with sqlite3.connect(self.db) as c:
            c.executescript(CREATE)
            c.execute('INSERT INTO neurons VALUES(11)')
            c.execute('INSERT INTO neuron_missions VALUES (23,11,"experimental")')
            c.execute('INSERT INTO runs VALUES (?,?)',('real-run','react-ui'))
            c.execute('INSERT INTO neuron_activity VALUES (1,?,11,1)',('real-run',))
            c.execute('INSERT INTO verification_reports VALUES(1,?,"ok",0.9,0.8,0.9,0.8,1)',('real-run',))
    def tearDown(self): self.temp.cleanup()
    def test_real_run_recorded_once(self):
        a=bridge_verified_user_run(self.db,'real-run')
        self.assertEqual(a['status'],'recorded')
        self.assertEqual(a['created'],[{'mission_id':23,'neuron_id':11}])
        self.assertEqual(bridge_verified_user_run(self.db,'real-run')['status'],'already_recorded')
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM neuron_evidence').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT source FROM neuron_evidence').fetchone()[0],'user_run_locally_verified')
    def test_fake_worker_cannot_record(self):
        with sqlite3.connect(self.db) as c:c.execute('UPDATE runs SET source="neuron_activity"')
        self.assertEqual(bridge_verified_user_run(self.db,'real-run')['reason'],'not_user_react_run')
    def test_no_verified_report(self):
        with sqlite3.connect(self.db) as c:c.execute('UPDATE verification_reports SET status="warning"')
        self.assertEqual(bridge_verified_user_run(self.db,'real-run')['reason'],'no_valid_verification_report')
    def test_no_activation(self):
        with sqlite3.connect(self.db) as c:c.execute('UPDATE neuron_activity SET activated=0')
        self.assertEqual(bridge_verified_user_run(self.db,'real-run')['reason'],'no_matching_neuronal_activation')
    def test_no_matching_mission(self):
        with sqlite3.connect(self.db) as c:c.execute('UPDATE neuron_missions SET status="disabled"')
        self.assertEqual(bridge_verified_user_run(self.db,'real-run')['reason'],'no_matching_neuronal_activation')
    def test_low_safety(self):
        with sqlite3.connect(self.db) as c:c.execute('UPDATE verification_reports SET safety_score=0.1')
        self.assertEqual(bridge_verified_user_run(self.db,'real-run')['reason'],'unsafe_verification')

if __name__ == '__main__':unittest.main()