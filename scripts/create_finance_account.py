"""Add the requested finance account without schema/data initialization.

Pass an existing database explicitly. Password is read from a prompt or
BOM_FINANCE_PASSWORD; never stored in source, backups' metadata or audit logs.
"""
import argparse
from datetime import datetime
import getpass
import os
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from backend.app import auth, models, services


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, required=True)
    args = parser.parse_args()
    target = args.database.resolve(strict=True)
    password = os.environ.get('BOM_FINANCE_PASSWORD') or getpass.getpass('Finance password: ')
    if len(password) < 6:
        raise SystemExit('Password must be at least 6 characters')
    engine = create_engine('sqlite://', creator=lambda: sqlite3.connect(target.as_uri() + '?mode=rw', uri=True))
    with Session(engine) as db:
        db.connection().exec_driver_sql('BEGIN IMMEDIATE')
        existing = db.scalar(select(models.User).where(models.User.username == 'finance'))
        if existing:
            if existing.role == 'finance' and existing.active and auth.verify_password(password, existing.password_hash):
                print('finance already exists with the requested role and password; unchanged')
                return
            raise SystemExit('finance already exists with different settings; refusing to overwrite')
        backup = target.parent / 'backups' / ('before-finance-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.db')
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target.as_uri() + '?mode=ro', uri=True) as source, sqlite3.connect(backup) as dest:
            source.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Backup integrity check failed')
        row = models.User(username='finance', password_hash=auth.hash_password(password),
                          display_name='财务', department='财务', role='finance', active=True)
        db.add(row)
        db.flush()
        services.audit(db, None, 'create', 'user', row.id, '按授权新增财务只读账号', after=services.user_dict(row))
        assert auth.verify_password(password, row.password_hash)
        db.commit()
        print('Created finance; role=finance; active=True; password verified')
        print('Backup:', backup)
    engine.dispose()


if __name__ == '__main__':
    main()
