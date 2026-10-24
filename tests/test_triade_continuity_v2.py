"""Continuity v2 must never trust the old v1 pointer or a tampered v2 image."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import triade_continuity_v2 as guard


def _fake_db(db: Path):
    with sqlite3.connect(db) as conn:
        for table in guard.MONOTONE:
            conn.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY)')
        conn.execute('INSERT INTO auth_users VALUES (1)')
        conn.execute('INSERT INTO auth_email_identities VALUES (1)')
        conn.execute('INSERT INTO neurons VALUES (1)')
        conn.execute('INSERT INTO autonomous_tasks VALUES (1)')
        conn.execute('INSERT INTO metabolic_cycle VALUES (1)')


def _fixture(tmp_path: Path, monkeypatch):
    root = tmp_path / 'Triade_580_Limpia'
    db = root / 'triade/memory/triade.db'
    db.parent.mkdir(parents=True)
    _fake_db(db)
    drive = tmp_path / 'Drive/Triade'
    drive.mkdir(parents=True)
    store = drive / 'continuidad_runtime/v2'
    monkeypatch.setattr(guard, 'ROOT', root)
    monkeypatch.setattr(guard, 'DRIVE', drive)
    monkeypatch.setattr(guard, 'STORE', store)
    monkeypatch.setattr(guard, 'INDEX', store / 'active_verified.json')

    def inspect(path: Path):
        state = guard._inspect(Path(path), immutable=Path(path) != db)
        return {'counts': state['counts'], 'lineage': guard.LINEAGE, 'integrity': 'ok'}

    monkeypatch.setitem(sys.modules, 'triade_colab_oneclick_runtime',
                        SimpleNamespace(DB=db, inspect_db=inspect))
    return db, drive, store


def test_publish_never_writes_legacy_pointer(tmp_path: Path, monkeypatch):
    db, drive, _store = _fixture(tmp_path, monkeypatch)
    legacy = drive / 'continuidad_runtime/v1/active.json'
    legacy.parent.mkdir(parents=True)
    legacy.write_text('invalid legacy pointer')
    assert guard.run()['status'] == 'preflight_only'
    assert not guard.INDEX.exists()
    assert guard.run(publish=True)['status'] == 'published_v2_verified'
    assert legacy.read_text() == 'invalid legacy pointer'
    verify = guard.run()['prior_v2']
    assert verify['counts']['autonomous_tasks'] == 1
    assert guard.run(publish=True)['status'] == 'published_v2_verified'
    with sqlite3.connect(db) as live:
        assert live.execute('SELECT COUNT(*) FROM autonomous_tasks').fetchone()[0] == 1


def test_v2_refuses_mutated_backup_sidecar(tmp_path: Path, monkeypatch):
    _db, _drive, store = _fixture(tmp_path, monkeypatch)
    guard.run(publish=True)
    idx = guard.INDEX.read_bytes()
    data = json.loads(idx)
    image = store / data['file']
    sidecar = image.with_suffix('.json')
    metadata = json.loads(sidecar.read_text())
    metadata['sha256'] = '0' * 64
    sidecar.write_text(json.dumps(metadata))
    with pytest.raises(RuntimeError, match='checksum'):
        guard.run(publish=True)
    assert guard.INDEX.read_bytes() == idx


def test_v2_rejects_monotone_regression(tmp_path: Path, monkeypatch):
    db, _drive, _store = _fixture(tmp_path, monkeypatch)
    guard.run(publish=True)
    with sqlite3.connect(db) as conn:
        conn.execute('DELETE FROM autonomous_tasks')
    with pytest.raises(RuntimeError, match='REGRESION'):
        guard.run()
