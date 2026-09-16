from pathlib import Path
import os
import sqlite3
import sys

from openpyxl import Workbook

root = Path(__file__).resolve().parents[2]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

from backend.app.v1_1_1_migration import apply_upgrade  # noqa: E402


source_database = Path(os.environ.get('BOM_E2E_SOURCE', str(root / 'runtime' / 'bom_v1.db'))).resolve()
test_database = root / "runtime" / "e2e.db"
if source_database == test_database.resolve():
    raise SystemExit('测试源库不能是将被重建的 e2e.db')
if not source_database.exists():
    raise SystemExit(f"初始数据库不存在：{source_database}")
for candidate in (test_database, Path(f"{test_database}-wal"), Path(f"{test_database}-shm")):
    if candidate.exists():
        candidate.unlink()
with sqlite3.connect(source_database) as source, sqlite3.connect(test_database) as target_db:
    source.backup(target_db)
with sqlite3.connect(test_database) as version_db:
    already_v12=version_db.execute("SELECT 1 FROM audit_events WHERE action='migrate_v1_2' LIMIT 1").fetchone()
if not already_v12:
    apply_upgrade(test_database, create_backup=False, write_reports=False)
from backend.app.v1_2_migration import apply_upgrade as upgrade_v12
upgrade_v12(test_database,create_backup=False,write_reports=False)
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from backend.app import models, auth
from backend.app.v1_2_demo import seed_in_session
test_engine=create_engine(f'sqlite:///{test_database.as_posix()}')
with Session(test_engine,expire_on_commit=False) as db:
    seed_in_session(db,db.scalar(select(models.User).where(models.User.role=='admin')))
    # Test credentials exist only in isolated e2e.db, never in the source/production database.
    for name, role, password in [('admin','admin','admin123'), ('dev','dev','dev12345'),
                                  ('product','product','product123'), ('guest','guest','viewer123')]:
        user = db.scalar(select(models.User).where(models.User.username == name))
        if not user:
            user = models.User(username=name, display_name=name, role=role, active=True)
            db.add(user)
        user.role, user.password_hash, user.active = role, auth.hash_password(password), True
    db.commit()
test_engine.dispose()
target = root / "runtime" / "e2e-material-import.xlsx"
target.parent.mkdir(parents=True, exist_ok=True)
workbook = Workbook()
sheet = workbook.active
sheet.title = "待导入原材料"
sheet.append(["物料识别码", "名称", "规格型号", "属性", "单位", "备注", "材料属性"])
sheet.append(["09.9899.01", "E2E导入专用垫片", "E2E-20260812", "外购", "pcs", "Playwright 自动化", "垫片"])
workbook.save(target)
print(target)
