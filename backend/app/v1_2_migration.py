"""Transactional V1.2 upgrade; no retention deletion, no writes before verified backup."""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.schema import CreateTable, CreateIndex
from sqlalchemy.dialects.sqlite import dialect

from . import models
from .config import settings
from .v1_1_1_migration import database_path


def apply_upgrade(path: Path | None = None, *, create_backup=True, write_reports=True, **_):
    target = (path or database_path()).resolve()
    if not target.is_file():
        raise FileNotFoundError(target)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    report = {'version': '1.2', 'database': str(target), 'deleted': [], 'disabled': [], 'backup': None}
    db = sqlite3.connect(target, timeout=30)
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('原数据库完整性检查失败，未执行升级')
        if create_backup:
            settings.backup_dir.mkdir(parents=True, exist_ok=True)
            backup = settings.backup_dir / f'bom-v1.2-before-{stamp}.db'
            with sqlite3.connect(backup) as dest:
                db.backup(dest)
                if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('备份验证失败，未执行升级')
            report['backup'] = str(backup)
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('BEGIN IMMEDIATE')
        for model in (models.PathAlternative, models.DeletedMaterialPromotion):
            table = model.__table__
            db.execute(str(CreateTable(table, if_not_exists=True).compile(dialect=dialect())))
            for index in table.indexes:
                db.execute(str(CreateIndex(index, if_not_exists=True).compile(dialect=dialect())))
        done = db.execute("SELECT 1 FROM audit_events WHERE action='migrate_v1_2'").fetchone()
        if not done:
            report['old_groups_removed'] = db.execute('SELECT count(*) FROM alternative_groups').fetchone()[0]
            db.execute('UPDATE bom_lines SET alternative_group_id=NULL')
            db.execute('DELETE FROM alternative_members')
            db.execute('DELETE FROM alternative_groups')
            db.execute("UPDATE items SET status='active' WHERE item_type='material' AND status IS NULL")
            for table, entity in [('items', 'item'), ('bom_lines', 'bom_line')]:
                maximum = db.execute(f'SELECT coalesce(max(id),0) FROM {table}').fetchone()[0]
                historical = db.execute('SELECT coalesce(max(entity_id),0) FROM audit_events WHERE entity_type=?', (entity,)).fetchone()[0]
                db.execute('INSERT INTO code_sequences(name,next_value) VALUES (?,?) ON CONFLICT(name) DO UPDATE SET next_value=max(next_value,excluded.next_value)', ('id_'+table, max(maximum, historical)+1))
            deleted = {r[0]:r for r in db.execute('SELECT id,code,name,unofficial_status FROM items WHERE deleted_at IS NOT NULL')}
            retained = {i for i,r in deleted.items() if r[3]=='archived'}
            # Fixed point: preserve deleted children of any retained/nondeleted parent.
            edges = list(db.execute('SELECT parent_item_id,child_item_id FROM bom_lines'))
            while True:
                next_retained = retained | {c for p,c in edges if c in deleted and (p not in deleted or p in retained)}
                if next_retained == retained:
                    break
                retained = next_retained
            remove = set(deleted)-retained
            for item_id in retained:
                db.execute("UPDATE items SET deleted_at=NULL,status='disabled' WHERE id=?", (item_id,))
                report['disabled'].append({'id':item_id,'code':deleted[item_id][1],'name':deleted[item_id][2]})
            for item_id in remove:
                for source_id, in db.execute('SELECT source_item_id FROM material_promotion_links WHERE target_item_id=?', (item_id,)).fetchall():
                    db.execute('INSERT INTO deleted_material_promotions(source_item_id,target_item_id,target_code,target_name,deleted_at) VALUES (?,?,?,?,?)', (source_id,item_id,deleted[item_id][1],deleted[item_id][2],datetime.now(timezone.utc).isoformat()))
                db.execute('DELETE FROM material_promotion_links WHERE target_item_id=? OR source_item_id=?', (item_id,item_id))
                db.execute('UPDATE items SET copied_from_id=NULL WHERE copied_from_id=?', (item_id,))
                db.execute('DELETE FROM bom_lines WHERE parent_item_id=?', (item_id,))
            for item_id in remove:
                db.execute('DELETE FROM items WHERE id=?', (item_id,))
                report['deleted'].append({'id':item_id,'code':deleted[item_id][1],'name':deleted[item_id][2]})
            db.execute("INSERT INTO audit_events(action,entity_type,reason,after_json,created_at) VALUES ('migrate_v1_2','database',?,?,?)", ('V1.2 清理旧选配和软删除数据',json.dumps(report,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
        if db.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('升级外键验证失败，已回滚')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise RuntimeError('升级完整性验证失败，已回滚')
        db.commit()
        report['status'] = 'success'
        report['already_upgraded'] = bool(done)
    except Exception as exc:
        db.rollback()
        report.update(status='failed', error=str(exc))
        raise
    finally:
        db.close()
        if write_reports:
            settings.report_dir.mkdir(parents=True, exist_ok=True)
            (settings.report_dir / f'v1.2-migration-{stamp}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--database',type=Path)
    parser.add_argument('--check-applied',action='store_true')
    args=parser.parse_args()
    if args.check_applied:
        import sys
        try:
            target=(args.database or database_path()).resolve()
            with sqlite3.connect(target.as_uri()+'?mode=ro',uri=True) as db:
                has_audit=db.execute("SELECT 1 FROM sqlite_master WHERE name='audit_events'").fetchone()
                applied=has_audit and db.execute("SELECT 1 FROM audit_events WHERE action='migrate_v1_2' LIMIT 1").fetchone()
            sys.exit(0 if applied else 1)
        except sqlite3.DatabaseError as exc:
            print(f'数据库版本检查失败：{exc}',file=sys.stderr)
            sys.exit(2)
    print(json.dumps(apply_upgrade(args.database),ensure_ascii=False,indent=2))
