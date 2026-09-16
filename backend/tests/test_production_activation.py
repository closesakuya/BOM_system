import json
import sqlite3
from contextlib import closing
from types import SimpleNamespace

import pytest

from backend.app import production_rebuild as rebuild


def create_db(path, value, marker=False):
    with closing(sqlite3.connect(path)) as db:
        db.execute('CREATE TABLE sample(value TEXT)')
        db.execute('INSERT INTO sample VALUES (?)', (value,))
        db.execute('CREATE TABLE audit_events(action TEXT)')
        if marker:
            db.execute("INSERT INTO audit_events VALUES ('production_rebuild')")
        db.commit()


def read_value(path):
    with closing(sqlite3.connect(path)) as db:
        return db.execute('SELECT value FROM sample').fetchone()[0]


def test_activation_requires_validation_and_preserves_verified_backup(tmp_path, monkeypatch):
    target, candidate = tmp_path / 'current.db', tmp_path / 'candidate.db'
    create_db(target, 'old'); create_db(candidate, 'new', marker=True)
    monkeypatch.setattr(rebuild, 'settings', SimpleNamespace(backup_dir=tmp_path/'backups', report_dir=tmp_path/'reports'))
    with pytest.raises(ValueError, match='验证报告'):
        rebuild.activate_database(candidate, target)
    assert read_value(target) == 'old'
    candidate.with_suffix('.report.json').write_text(json.dumps({'validated': True}), encoding='utf-8')
    result = rebuild.activate_database(candidate, target)
    assert read_value(target) == 'new'
    assert read_value(result['backup']) == 'old'
    assert not candidate.exists()
    assert list((tmp_path/'reports').glob('production-activation-*.json'))


def test_activation_rejects_nonproduction_candidate_without_changing_current(tmp_path):
    target, candidate = tmp_path / 'current.db', tmp_path / 'candidate.db'
    create_db(target, 'old'); create_db(candidate, 'invalid')
    candidate.with_suffix('.report.json').write_text(json.dumps({'validated': True}), encoding='utf-8')
    with pytest.raises(ValueError, match='重建标记'):
        rebuild.activate_database(candidate, target)
    assert read_value(target) == 'old'
