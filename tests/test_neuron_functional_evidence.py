import sqlite3
import tempfile
import unittest
from pathlib import Path
from triade.neurons.functional_evidence import assess_answer, register_actual_probe, functional_comparison

SCHEMA='''
CREATE TABLE neurons(id INTEGER PRIMARY KEY,name TEXT,domain TEXT);
CREATE TABLE runs(run_id TEXT PRIMARY KEY,source TEXT,status TEXT NOT NULL DEFAULT 'ok');
CREATE TABLE neuron_activity(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT,neuron_id INTEGER,activated INTEGER,created_at TEXT);
CREATE TABLE verification_reports(id INTEGER PRIMARY KEY AUTOINCREMENT,run_id TEXT,status TEXT,safety_score REAL,errors TEXT NOT NULL DEFAULT '[]',warnings TEXT NOT NULL DEFAULT '[]');
CREATE TABLE neuron_education_sessions(session_id TEXT PRIMARY KEY,neuron_id INTEGER,created_at TEXT);
'''
class ProbeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Path(self.temp.name)/'memory.db'
        self.before='2026-10-20T10:00:00+00:00'
        self.after='2026-10-21T10:00:00+00:00'
        with sqlite3.connect(self.db) as c:
            c.executescript(SCHEMA)
            c.execute('INSERT INTO neurons VALUES(11,?,?)',('Neurona Visual','visual_semantics'))
            c.execute('INSERT INTO neuron_education_sessions VALUES(?,?,?)',('session-1',11,self.after))
    def tearDown(self):self.temp.cleanup()
    def run_event(self, run, when, *, origin='neuron_functional_probe', activated=1, safety=.9, verifier='ok', errors='[]', warnings='[]', run_status='ok'):
        with sqlite3.connect(self.db) as c:
            c.execute('INSERT INTO runs(run_id,source,status) VALUES(?,?,?)',(run,origin,run_status))
            c.execute('INSERT INTO neuron_activity(run_id,neuron_id,activated,created_at) VALUES(?,?,?,?)',(run,11,activated,when))
            c.execute('INSERT INTO verification_reports(run_id,status,safety_score,errors,warnings) VALUES(?,?,?,?,?)',(run,verifier,safety,errors,warnings))
    def test_exact_rubric_not_string_containment(self):
        self.assertEqual(assess_answer('py1','4')['score'],1.0)
        self.assertEqual(assess_answer('py1','La respuesta es 4')['score'],0.0)
    def test_requires_real_run(self):
        self.run_event('faux',self.before,origin='neuron_activity')
        with self.assertRaisesRegex(ValueError,'Origen'):register_actual_probe(self.db,run_id='faux',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
    def test_requires_real_activation(self):
        self.run_event('faux',self.before,activated=0)
        with self.assertRaisesRegex(ValueError,'participó'):register_actual_probe(self.db,run_id='faux',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
    def test_requires_verified_safety(self):
        self.run_event('faux',self.before,safety=.2)
        with self.assertRaisesRegex(ValueError,'inseguro'):register_actual_probe(self.db,run_id='faux',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
    def test_benign_semantic_quarantine_warning_allowed(self):
        warning='["Gobierno semántico dejó en cuarentena 3 recuerdo(s) recuperado(s) no autorizado(s)."]'
        self.run_event('quarantine',self.before,verifier='warning',warnings=warning)
        x=register_actual_probe(self.db,run_id='quarantine',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
        self.assertEqual(x['status'],'recorded')
    def test_another_warning_blocked(self):
        self.run_event('degraded',self.before,verifier='warning',warnings='["Cristal detectó degradación temporal"]')
        with self.assertRaisesRegex(ValueError,'inseguro'):
            register_actual_probe(self.db,run_id='degraded',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
    def test_mixed_warning_blocked(self):
        warnings='["Gobierno semántico dejó en cuarentena 3 recuerdo(s) recuperado(s) no autorizado(s).","Cristal detectó degradación temporal"]'
        self.run_event('mixed',self.before,verifier='warning',warnings=warnings)
        with self.assertRaisesRegex(ValueError,'inseguro'):
            register_actual_probe(self.db,run_id='mixed',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
    def test_warning_with_errors_blocked(self):
        warning='["Gobierno semántico dejó en cuarentena 3 recuerdo(s) recuperado(s) no autorizado(s)."]'
        self.run_event('errors',self.before,verifier='warning',warnings=warning,errors='["Error real"]')
        with self.assertRaisesRegex(ValueError,'inseguro'):
            register_actual_probe(self.db,run_id='errors',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
    def test_warning_with_low_safety_blocked(self):
        warning='["Gobierno semántico dejó en cuarentena 3 recuerdo(s) recuperado(s) no autorizado(s)."]'
        self.run_event('low',self.before,verifier='warning',warnings=warning,safety=0.59)
        with self.assertRaisesRegex(ValueError,'inseguro'):
            register_actual_probe(self.db,run_id='low',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
    def test_malformed_warning_json_blocked(self):
        self.run_event('broken',self.before,verifier='warning',warnings='not-json')
        with self.assertRaisesRegex(ValueError,'inseguro'):
            register_actual_probe(self.db,run_id='broken',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
    def test_incomplete_run_blocked(self):
        self.run_event('incomplete',self.before,run_status='warning')
        with self.assertRaisesRegex(ValueError,'Origen o estado'):
            register_actual_probe(self.db,run_id='incomplete',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
    def test_wrong_domain_blocked(self):
        self.run_event('true-pre',self.before)
        with self.assertRaisesRegex(ValueError,'competencia funcional'):
            register_actual_probe(self.db,run_id='true-pre',neuron_id=11,case_id='py1',phase='pre',answer='4')
    def test_no_retroactive_baseline(self):
        self.run_event('too-late',self.after)
        self.assertEqual(register_actual_probe(self.db,run_id='too-late',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')['status'],'recorded')
        with sqlite3.connect(self.db) as c:
            self.assertFalse(functional_comparison(c,neuron_id=11,session_id='session-1',lesson_at=self.after)['ready'])
    def test_post_cannot_precede_lesson(self):
        self.run_event('faux',self.before)
        with self.assertRaisesRegex(ValueError,'precede'):register_actual_probe(self.db,run_id='faux',neuron_id=11,case_id='vis1',phase='post',session_id='session-1',answer='#ff0000')
    def test_idempotent_and_provenance(self):
        self.run_event('true-pre',self.before)
        a=register_actual_probe(self.db,run_id='true-pre',neuron_id=11,case_id='vis1',phase='pre',answer='#FF0000')
        b=register_actual_probe(self.db,run_id='true-pre',neuron_id=11,case_id='vis1',phase='pre',answer='#FF0000')
        self.assertEqual(a['status'],'recorded');self.assertEqual(b['status'],'already_recorded')
        with sqlite3.connect(self.db) as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM neuron_functional_assessments').fetchone()[0],1)
    def test_not_enough_distinct_cases(self):
        self.run_event('pre',self.before)
        register_actual_probe(self.db,run_id='pre',neuron_id=11,case_id='vis1',phase='pre',answer='#ff0000')
        for i in range(5):
            run=f'post{i}';self.run_event(run,f'2026-10-22T10:{i:02d}:00+00:00')
            register_actual_probe(self.db,run_id=run,neuron_id=11,case_id='vis1',phase='post',session_id='session-1',answer='#ff0000')
        with sqlite3.connect(self.db) as c:
            x=functional_comparison(c,neuron_id=11,session_id='session-1',lesson_at=self.after)
            self.assertFalse(x['ready'])
            self.assertEqual(x['post_distinct_runs'],5)
            self.assertEqual(x['post_distinct_cases'],1)
    def test_pre_post_same_domain_measured(self):
        for i,case in enumerate(('vis1','vis2','vis3')):
            run=f'pre{i}';self.run_event(run,f'2026-10-20T09:0{i}:00+00:00')
            register_actual_probe(self.db,run_id=run,neuron_id=11,case_id=case,phase='pre',answer='incorrecto')
        for i,case in enumerate(('vis1','vis2','vis3','vis1','vis2')):
            run=f'post{i}';self.run_event(run,f'2026-10-22T10:{i:02d}:00+00:00')
            ans={'vis1':'#ff0000','vis2':'negro','vis3':'horizontal'}[case]
            register_actual_probe(self.db,run_id=run,neuron_id=11,case_id=case,phase='post',session_id='session-1',answer=ans)
        with sqlite3.connect(self.db) as c:
            x=functional_comparison(c,neuron_id=11,session_id='session-1',lesson_at=self.after)
            self.assertTrue(x['ready']);self.assertEqual(x['delta'],1.0)
            self.assertFalse(x['causal_attribution'])

if __name__=='__main__':unittest.main()