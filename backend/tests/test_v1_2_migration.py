import sqlite3
from datetime import datetime,timezone
from sqlalchemy import select
from backend.app import models,schemas,services
from backend.app.v1_2_migration import apply_upgrade


def test_migration_removes_unreferenced_retains_referenced_and_is_idempotent(db,tmp_path):
    actor=db.scalar(select(models.User))
    def make(code):return services.create_item(db,schemas.ItemCreate(item_type='material',code=code,name=code,source_type='purchased',similarity_confirmed=True),actor)
    free=make('10.9301.0');child=make('10.9302.0');parent=make('10.9303.0')
    services.add_bom_line(db,parent,schemas.BOMComponentIn(child_item_id=child.id,quantity=1),actor,'测试引用')
    free.deleted_at=child.deleted_at=datetime.now(timezone.utc);db.commit()
    source=db.get_bind().url.database
    target=tmp_path/'migration.db'
    with sqlite3.connect(source) as src,sqlite3.connect(target) as dst:src.backup(dst)
    result=apply_upgrade(target,create_backup=False,write_reports=False)
    assert [r['code'] for r in result['deleted']]==['10.9301.0']
    assert [r['code'] for r in result['disabled']]==['10.9302.0']
    again=apply_upgrade(target,create_backup=False,write_reports=False)
    assert again['already_upgraded'] is True
    with sqlite3.connect(target) as conn:
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert not conn.execute('PRAGMA foreign_key_check').fetchall()


def test_migration_rolls_back_all_changes_on_failure(db,tmp_path):
    import pytest
    actor=db.scalar(select(models.User))
    item=services.create_item(db,schemas.ItemCreate(code='10.9400.0',item_type='material',name='迁移回滚',source_type='purchased',similarity_confirmed=True),actor)
    item.status=None
    group=models.AlternativeGroup(name='原旧组',item_type='material',default_item_id=item.id,active=True)
    db.add(group);db.commit()
    target=tmp_path/'rollback.db'
    with sqlite3.connect(db.get_bind().url.database) as src,sqlite3.connect(target) as dst:src.backup(dst)
    with sqlite3.connect(target) as conn:
        conn.execute("CREATE TRIGGER fail_upgrade BEFORE UPDATE ON items BEGIN SELECT RAISE(ABORT,'模拟升级失败'); END")
    with pytest.raises(sqlite3.IntegrityError,match='模拟升级失败'):
        apply_upgrade(target,create_backup=False,write_reports=False)
    with sqlite3.connect(target) as conn:
        assert conn.execute('SELECT count(*) FROM alternative_groups').fetchone()[0]==1
        assert conn.execute("SELECT count(*) FROM audit_events WHERE action='migrate_v1_2'").fetchone()[0]==0
        assert conn.execute('SELECT status FROM items WHERE id=?',(item.id,)).fetchone()[0] is None


def test_upgraded_database_rejects_old_global_endpoints(client,headers,db):
    services.audit(db,None,'migrate_v1_2','database',None,'已升级');db.commit()
    response=client.post('/api/alternatives',headers=headers,json={'name':'旧组','item_type':'material','default_item_id':1,'member_item_ids':[2],'reason':'旧页面写入'})
    assert response.status_code==410
