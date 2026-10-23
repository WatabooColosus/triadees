import hashlib
import json
import pathlib
import sqlite3
from types import SimpleNamespace

from scripts.triade_colab_continuity_guard import (
    _image_from_live_sqlite,
    safe_snapshot,
)

class Coordinator:
    def __init__(self, root):
        self.DRIVE = root/'Drive'; self.DRIVE.mkdir()
        self.STORE=self.DRIVE/'continuidad_runtime'/'v1'; self.STORE.mkdir(parents=True)
        self.INDEX=self.STORE/'active.json'
        self.DB=root/'triade.db'
        self.engine=SimpleNamespace(STATE=root/'state',repo_status=lambda:'test-sha')
        self.engine.STATE.mkdir()
        self.SUMMARY=('neurons','autonomous_tasks','neuron_education_sessions','neuron_education_applications', 'metabolic_cycle','auth_users','auth_email_identities','worker_runs','governed_research_runs')
        with sqlite3.connect(self.DB) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript('''CREATE TABLE neurons(id INTEGER PRIMARY KEY);
            CREATE TABLE autonomous_tasks(id INTEGER PRIMARY KEY);
            CREATE TABLE neuron_education_sessions(id INTEGER PRIMARY KEY);
            CREATE TABLE neuron_education_applications(id INTEGER PRIMARY KEY);
            CREATE TABLE metabolic_cycle(id INTEGER PRIMARY KEY);
            CREATE TABLE auth_users(user_id TEXT PRIMARY KEY);
            CREATE TABLE auth_email_identities(id INTEGER PRIMARY KEY);
            CREATE TABLE worker_runs(id INTEGER PRIMARY KEY);
            CREATE TABLE governed_research_runs(id INTEGER PRIMARY KEY);''')
            conn.execute("INSERT INTO auth_users VALUES('ownerA')")
            conn.execute('INSERT INTO neurons VALUES(1)')
            conn.executemany('INSERT INTO autonomous_tasks VALUES(?)',[(i,) for i in range(1,13)])
            conn.executemany('INSERT INTO metabolic_cycle VALUES(?)',[(i,) for i in range(1,8)])
        self._held_wal_conn=sqlite3.connect(self.DB)
        self._held_wal_conn.execute('PRAGMA journal_mode=WAL')
        self._held_wal_conn.execute('INSERT INTO autonomous_tasks VALUES(13)')
        self._held_wal_conn.commit()

    def inspect_db(self,path):
        with sqlite3.connect('file:'+str(pathlib.Path(path).resolve())+'?mode=ro',uri=True) as conn:
            assert conn.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            counts={k:conn.execute(f'SELECT COUNT(*) FROM "{k}"').fetchone()[0] for k in self.SUMMARY}
            u=conn.execute('SELECT user_id FROM auth_users').fetchall()
        lineage=hashlib.sha256('\n'.join(sorted(x[0] for x in u)).encode()).hexdigest()[:16]
        return {'lineage':lineage,'counts':counts,'integrity':'ok'}
    def digest(self,p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
    def atomic_json(self,p,d):p.write_text(json.dumps(d),encoding='utf8')
    def validated_snapshot(self,p):
        meta=json.loads(p.with_suffix('.json').read_text())
        if meta['size']!=p.stat().st_size or meta['sha256']!=self.digest(p):return None
        return {'info':self.inspect_db(p)}

def test_image_consolidates_wal(tmp_path):
    c=Coordinator(tmp_path)
    dest=tmp_path/'private.db'
    _image_from_live_sqlite(c.DB,dest)
    assert c.inspect_db(dest)['counts']['autonomous_tasks']==13
    assert not dest.with_name(dest.name+'-wal').exists()
    assert sqlite3.connect(dest).execute('pragma journal_mode').fetchone()[0]=='delete'
    c._held_wal_conn.close()

def test_pointer_published_with_exact_standalone_counts(tmp_path):
    c=Coordinator(tmp_path)
    before=c.inspect_db(c.DB)
    # Existing *wrong* index claims 12 rows for a standalone older file with 5.
    older=c.STORE/'memoria-antigua.sqlite3'
    _image_from_live_sqlite(c.DB,older)
    with sqlite3.connect(older) as conn:
        conn.execute('DELETE FROM autonomous_tasks WHERE id > 5')
    older_meta={'sha256':c.digest(older),'size':older.stat().st_size}
    c.atomic_json(older.with_suffix('.json'),older_meta)
    c.atomic_json(c.INDEX,{'file':older.name,'lineage':before['lineage'],
          'sha256':older_meta['sha256'],'counts':before['counts']})
    old_index=c.INDEX.read_text()
    result=safe_snapshot(c, force=True)
    assert result['status']=='saved'
    index=json.loads(c.INDEX.read_text())
    image=c.STORE/index['file']
    assert image.exists()
    assert c.inspect_db(image)['counts']==index['counts']
    assert index['counts']['autonomous_tasks']==13
    assert older.exists() and c.INDEX.read_text()!=old_index
    assert list((c.STORE/'index_history_guarded').glob('active-before-*.json'))
    assert json.loads(list((c.STORE/'index_history_guarded').glob('active-before-*.json'))[0].read_text())['file']==older.name
    c._held_wal_conn.close()

def test_fails_closed_on_count_regression(tmp_path):
    c=Coordinator(tmp_path)
    data=c.inspect_db(c.DB)
    bad=dict(data['counts']);bad['autonomous_tasks']=100000
    c.atomic_json(c.INDEX,{'lineage':data['lineage'],'file':'existing.sqlite3', 'counts':bad, 'sha256':'old'})
    old=c.INDEX.read_text()
    import pytest
    with pytest.raises(RuntimeError,match='CONTINUIDAD_PROTEGIDA'):
        safe_snapshot(c,force=True)
    assert c.INDEX.read_text()==old
    c._held_wal_conn.close()