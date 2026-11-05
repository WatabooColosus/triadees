import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from tools import triade_colab_r7_control as ctl

class MockR5:
    def __init__(self,home):
        self.BASE=home/'drive'/'Triade';self.BASE.mkdir(parents=True)
        self.WORK=home/'work';self.WORK.mkdir()
        self.ROOT=home/'Triade';self.ROOT.mkdir()
        self.DB=self.ROOT/'triade.db'
    def db_info(self,p,allow_live_wal=False):
        with sqlite3.connect(p) as c:
            rows={x[0] for x in c.execute('select name from sqlite_master where type="table"')}
            if 'neurons' not in rows: return {'status':'error'}
            counts={k:c.execute(f'select count(*) from {k}').fetchone()[0] for k in ctl.WATERMARK_TABLES if k in rows}
            return {'status':'ok','owner_fingerprint':'abc123owner','counts':counts}
    def _owner_account_status(self,p):return True
    def check_working_identity(self):return True

def make_db(path,n=3):
    with sqlite3.connect(path) as c:
        for t in ctl.WATERMARK_TABLES:
            c.execute(f'create table {t}(id integer primary key)')
        c.execute('create table neuron_activity(id integer primary key,activated integer)')
        c.execute('create table worker_events(id integer primary key)')
        c.executemany('insert into neurons(id) values(?)',[(i,) for i in range(1,n+1)])
        c.execute('insert into auth_users(id) values(1)')

def proof(r5):
    ctl._atomic_json(r5.WORK/'restore_proof.json',{'source_sha256':'a'*64,'owner_fingerprint':'abc123owner','counts':r5.db_info(r5.DB)['counts']})

class R7Test(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.home=Path(self.temp.name)
        self.r=MockR5(self.home);make_db(self.r.DB);proof(self.r)
    def tearDown(self):self.temp.cleanup()
    def test_backup_is_verified_and_has_pointer(self):
        result=ctl._save_r7_snapshot(self.r)
        self.assertEqual(result['status'],'verified_backup_saved')
        v=ctl._verify_r7(self.r)
        self.assertEqual(v['status'],'verified')
        self.assertEqual(v['counts']['neurons'],3)
    def test_tampered_backup_blocks_selection(self):
        ctl._save_r7_snapshot(self.r)
        v=ctl._verify_r7(self.r)
        with open(v['path'],'ab') as f:f.write(b'tamper')
        self.assertEqual(ctl._verify_r7(self.r)['status'],'blocked')
    def test_monotone_review_restores_pre_api(self):
        source=self.home/'candidate.sqlite3';make_db(source,5)
        root=self.r.BASE/'operacion_colab_r5'/'ramas_en_revision'/('a'*16);root.mkdir(parents=True)
        index={'status':'review_branch_only','source_v2_sha256':'a'*64,'lineage':'90e9a51dd7ffef31',
               'file':'review.sqlite3','sha256':ctl._sha(source),'counts':self.r.db_info(source)['counts'],'date':'2026-10-25T12:00:00Z'}
        shutil.copyfile(source,root/index['file'])
        ctl._atomic_json(root/'latest_review.json',index);ctl._atomic_json(root/'review.json',index)
        result=ctl.restore_best_review(self.r)
        self.assertEqual(result['status'],'restored_review_guardian')
        self.assertEqual(ctl._db_counts(self.r.DB)['neurons'],5)
    def test_block_if_last_observed_greater_than_backup(self):
        ctl._save_r7_snapshot(self.r)
        high={'counts':{'neurons':6}}
        ctl._atomic_json(self.r.BASE/'operacion_colab_r7'/'ultimo_estado_observado.json',high)
        with self.assertRaisesRegex(RuntimeError,'más antigua'):
            ctl.restore_best_review(self.r)
    def test_no_review_uses_current_v2(self):
        v=ctl.restore_best_review(self.r)
        self.assertEqual(v['status'],'keep_r5_v2')

if __name__=='__main__':unittest.main(verbosity=2)