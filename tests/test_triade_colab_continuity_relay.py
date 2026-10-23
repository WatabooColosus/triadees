"""The previous saver must be fenced and joined before publishing new index."""
import json
import sys
import threading
from pathlib import Path
from types import FunctionType, ModuleType, SimpleNamespace

import pytest

from scripts import triade_colab_continuity_relay as handover


def _legacy_atomic_json(path, data):
    return data


def _legacy_snapshot_once():
    return atomic_json('/tmp/triade-legacy', {'counts': {'autonomous_tasks': 0}})


def _legacy_saver_worker():
    while not STOP.wait(50):
        snapshot_once()


# Static definitions for the legacy notebook's global symbol names. The test
# rebinds each function to an isolated namespace through FunctionType, so the
# worker never touches these module-level bindings.
STOP = threading.Event()
atomic_json = _legacy_atomic_json
snapshot_once = _legacy_snapshot_once


def _legacy_thread():
    old = {'threading': threading, 'STOP': threading.Event()}
    # Give real functions independent global namespaces without executing
    # dynamically supplied source strings. This simulates a stale notebook.
    old['atomic_json'] = FunctionType(_legacy_atomic_json.__code__, old)
    old['snapshot_once'] = FunctionType(_legacy_snapshot_once.__code__, old)
    old['worker'] = FunctionType(_legacy_saver_worker.__code__, old)
    t = threading.Thread(target=old['worker'], name=handover.SAVER_NAME, daemon=True)
    t.start()
    return t, old


def test_old_saver_stops_without_stopping_unrelated_worker():
    t, ns = _legacy_thread()
    otherstop = threading.Event()
    other = threading.Thread(target=lambda: otherstop.wait(50), name='TriadeLiveWorker', daemon=True)
    other.start()
    assert handover._source_globals(t) is ns
    ns['STOP'].set()
    t.join(3)
    assert not t.is_alive()
    assert other.is_alive()
    otherstop.set()
    other.join(3)


def test_fence_rejects_legacy_index_but_allows_guarded(tmp_path: Path):
    idx = tmp_path / 'active.json'
    calls=[]
    def writer(p,d):
        calls.append((p,d))
    ns={'atomic_json':writer}
    handover._fence_legacy_index(ns,idx)
    with pytest.raises(RuntimeError,match='escritor anterior'):
        ns['atomic_json'](idx,{'lineage':handover.EXPECTED_LINEAGE})
    assert calls == []
    ns['atomic_json'](idx,{'guard':handover.GUARD_VERSION})
    assert len(calls) == 1
    handover._fence_legacy_index(ns,idx)
    ns['atomic_json'](tmp_path/'manifest.json',{})
    assert len(calls) == 2


def test_reject_unknown_saver_without_stopping(tmp_path):
    gate=threading.Event()
    t=threading.Thread(target=lambda:gate.wait(50),name=handover.SAVER_NAME,daemon=True)
    t.start()
    with pytest.raises(RuntimeError,match='escritor desconocido|no inspeccionable'):
        handover._source_globals(t)
    assert not gate.is_set()
    gate.set();t.join(3)


def test_execute_replaces_stale_periodic_and_writes_guarded_index(tmp_path,monkeypatch):
    oldt, oldns = _legacy_thread()
    previous = {'lineage':handover.EXPECTED_LINEAGE,'file':'old.sqlite3',
                'counts': {'autonomous_tasks':10,'auth_users':1}}
    index=tmp_path/'active.json'
    index.write_text(json.dumps(previous))
    module=ModuleType('triade_colab_oneclick_runtime')
    module.DB=tmp_path/'live.db'
    module.INDEX=index
    module.STORE=tmp_path
    module.SNAP_INTERVAL_SECONDS=600
    module.THREAD=None
    module.STOP=threading.Event()
    module.BACKUP_MUTEX=threading.RLock()
    module.original_writes=[]
    def inspect_db(path):
        return {'lineage':handover.EXPECTED_LINEAGE,'integrity':'ok','counts':
                {'autonomous_tasks':50,'auth_users':1}}
    module.inspect_db=inspect_db
    def atomic_json(path,payload):
        module.original_writes.append((path,payload))
        Path(path).write_text(json.dumps(payload))
    module.atomic_json=atomic_json
    def original_snapshot(*, force=False):
        module.atomic_json(index,previous)
    module.snapshot_once=original_snapshot
    def background_saver():
        module.STOP.clear()
        def worker():
            while not module.STOP.wait(600):
                module.snapshot_once()
        module.THREAD=threading.Thread(target=worker,name=handover.SAVER_NAME,daemon=True)
        module.THREAD.start()
        return {'status':'running'}
    module.background_saver=background_saver
    monkeypatch.setitem(sys.modules,module.__name__,module)
    def fake_install(*,publish_one):
        def protected(*,force=False):
            output={'file':'new.sqlite3','lineage':handover.EXPECTED_LINEAGE,
                    'counts':inspect_db(None)['counts'],'guard':handover.GUARD_VERSION}
            module.atomic_json(index,output)
            return {'status':'saved', 'counts':output['counts']}
        protected._triade_verified_continuity=True
        module.snapshot_once=protected
    monkeypatch.setattr(handover,'_load_guard',lambda:SimpleNamespace(install=fake_install))
    try:
        outcome=handover.execute()
        assert outcome['status']=='single_guarded_writer'
        assert outcome['legacy_savers_stopped']>=1
        assert outcome['active_savers']==1
        assert not oldt.is_alive()
        assert oldns['snapshot_once'] is module.snapshot_once
        assert oldns['background_saver'] is module.background_saver
        assert json.loads(index.read_text())['guard']==handover.GUARD_VERSION
        with pytest.raises(RuntimeError,match='escritor anterior'):
            oldns['atomic_json'](index,previous)
    finally:
        module.STOP.set()
        if module.THREAD: module.THREAD.join(2)
        oldns['STOP'].set()
        oldt.join(2)
