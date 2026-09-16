"""Build a validated production database separately; activate only with explicit --activate."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, delete, event, select, text
from sqlalchemy.orm import Session

from . import auth, models, services
from .config import PROJECT_ROOT, settings
from .database import Base
from .machine_model_backfill import classify_machine_name
from .migration import LEGACY_PATH, read_code_rules, read_legacy
from .path_bom import EffectiveBOM, configuration_dict

EXCLUDED = {'J00.001.01', 'Y13.3005.0'}
ACCOUNT_ROLES = {'admin': ('admin', '管理员'), 'dev': ('dev', '研发'),
                 'product': ('product', '生产'), 'guest': ('guest', '访客')}


def transform_source(records, relationships):
    records = {code: dict(row) for code, row in records.items() if code not in EXCLUDED}
    relationships = [dict(row) for row in relationships
                     if row['parent_code'] not in EXCLUDED and row['child_code'] not in EXCLUDED]
    zero_adjustments = []
    for row in relationships:
        if row['quantity'] == 0:
            zero_adjustments.append({**row, 'before_quantity': '0', 'after_quantity': '1'})
            row['quantity'] = Decimal(1)
    children = defaultdict(list)
    for row in relationships:
        children[row['parent_code']].append(row)
    groups = {code: children[code] for code in records if code.startswith('X')}
    for code, rows in groups.items():
        if not rows or any(records[r['child_code']]['item_type'] != 'material' for r in rows):
            raise ValueError(f'{code} 的候选必须全部为原材料且不能为空')
        if len({r['child_code'] for r in rows}) != len(rows):
            raise ValueError(f'{code} 的候选重复，禁止自动合并选配')
        if len({r['quantity'] for r in rows}) != 1:
            raise ValueError(f'{code} 候选数量不一致，需人工确认')
    merged = {}
    converted = []
    duplicates = []
    for row in relationships:
        if row['parent_code'] in groups:
            continue
        source_code = row['child_code']
        if source_code in groups:
            options = groups[source_code]
            row = {**row, 'child_code': options[0]['child_code'],
                   'quantity': row['quantity'] * options[0]['quantity'], 'x_source': source_code,
                   'candidates': [r['child_code'] for r in options]}
            converted.append({'parent': row['parent_code'], 'source': source_code,
                              'selected': row['child_code'], 'quantity': str(row['quantity']),
                              'candidates': row['candidates']})
        parent, child = records[row['parent_code']], records[row['child_code']]
        if child['item_type'] not in services.ALLOWED_CHILDREN[parent['item_type']]:
            raise ValueError(f"不允许的组成类型：{row['parent_code']} → {row['child_code']}")
        if row['child_code'].startswith('99.'):
            raise ValueError(f"未正式子项引用：{row['parent_code']} → {row['child_code']}")
        if row['quantity'] <= 0:
            raise ValueError(f"组成数量必须大于零：{row['parent_code']} → {row['child_code']}")
        key = (row['parent_code'], row['child_code'])
        if key in merged:
            if row.get('x_source') or merged[key].get('x_source'):
                raise ValueError(f'X 转换发生同层重复，禁止自动合并：{key}')
            duplicates.append({'parent': key[0], 'child': key[1], 'quantity': str(row['quantity'])})
            merged[key]['quantity'] += row['quantity']
        else:
            merged[key] = row
    for row in merged.values():
        for candidate in row.get('candidates', []):
            if candidate != row['child_code'] and (row['parent_code'], candidate) in merged:
                raise ValueError(f"备选已存在于同层：{row['parent_code']} → {candidate}")
    records = {k: v for k, v in records.items() if k not in groups}
    for code, record in records.items():
        if code.startswith('99.') and (not re.fullmatch(r'99\.\d{4}\.\d', code) or record['item_type'] != 'material'):
            raise ValueError(f'未正式编码格式或类型不合法：{code}')
    return records, list(merged.values()), {'excluded_codes': sorted(EXCLUDED), 'x_groups_removed': len(groups),
                                           'converted_positions': converted, 'merged_duplicate_rows': duplicates,
                                           'zero_quantity_adjustments': zero_adjustments}


def load_accounts(path: Path | None):
    if path is None:
        values = {name: getpass.getpass(f'{label} ({name}) 初始密码：')
                  for name, (_, label) in ACCOUNT_ROLES.items()}
    elif path.suffix.lower() == '.json':
        values = json.loads(path.read_text(encoding='utf-8-sig'))
    else:
        # Local requirements file is ignored by Git. Never copy its passwords to reports/logs.
        content = path.read_text(encoding='utf-8-sig')
        values = {}
        for name in ACCOUNT_ROLES:
            matches = re.findall(rf'^\s*{name}[ \t]+([^\s]+)[ \t]*$', content, re.MULTILINE)
            if len(matches) != 1:
                raise ValueError(f'本地账号配置必须且只能提供一次 {name} 的初始密码')
            values[name] = matches[0]
    if set(values) != set(ACCOUNT_ROLES) or any(not isinstance(v, str) or len(v) < 6 for v in values.values()):
        raise ValueError('需要四个账号的密码，每个至少 6 个字符')
    return values


def build_database(target: Path, accounts: dict[str, str], source: Path = LEGACY_PATH, *, demo=True):
    target = target.resolve()
    source = source.resolve()
    if target == Path(settings.database_url.removeprefix('sqlite:///')).resolve():
        raise ValueError('必须先构建独立候选数据库，不得直接覆盖运行数据库')
    records, relationships, report = read_legacy(source)
    if report['issues'] or report['unresolved_collisions']:
        raise ValueError('原始数据存在错误，已停止构建')
    records, relationships, conversion = transform_source(records, relationships)
    report.update(conversion)
    report['key_codes_normalized'] = []
    for code, record in records.items():
        original = record['auxiliary_code'] if record['item_type'] == 'material' else None
        normalized = services.normalize_key_component_code(original)
        record['normalized_key_code'] = normalized
        if original != normalized:
            report['key_codes_normalized'].append({'code': code, 'before': original, 'after': normalized})
    report['source_sha256'] = hashlib.sha256(source.read_bytes()).hexdigest()
    rules = read_code_rules()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental overwrite of any existing database.
    with target.open('xb'):
        pass
    engine = create_engine(f'sqlite:///{target.as_posix()}')

    @event.listens_for(engine, 'connect')
    def configure(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')

    try:
        Base.metadata.create_all(engine)
        with engine.begin() as conn:
            for operation in ('UPDATE', 'DELETE'):
                conn.execute(text(f"CREATE TRIGGER audit_events_no_{operation.lower()} BEFORE {operation} ON audit_events BEGIN SELECT RAISE(ABORT,'audit events are immutable'); END"))
        with Session(engine, expire_on_commit=False) as db:
            users = {}
            for name, (role, label) in ACCOUNT_ROLES.items():
                user = models.User(username=name, password_hash=auth.hash_password(accounts[name]),
                                   display_name=label, role=role, active=True)
                db.add(user); users[name] = user
            db.flush()
            actor = users['admin']
            items = {}
            for code, record in records.items():
                body, version, number = services.parse_code(code)
                pending = code.startswith('99.')
                item = models.Item(code=code, code_body=body, version_label=version,
                                   version_number=number, version_series=body,
                                   **{k: record[k] for k in ('item_type', 'auxiliary_code', 'name', 'specification',
                                       'source_type', 'unit', 'remark', 'previous_version_name', 'invoice_name', 'material_attribute')},
                                   key_component_code=record['normalized_key_code'],
                                   is_formally_imported=not pending, unofficial_status='pending' if pending else None,
                                   status='active' if record['item_type'] == 'material' else 'trial',
                                   machine_model=classify_machine_name(record['name']) if record['item_type'] == 'machine' else None,
                                   requires_assembly=False, created_by=actor.id, updated_by=actor.id)
                db.add(item); items[code] = item
            db.flush()
            order = Counter()
            for row in relationships:
                parent, child = items[row['parent_code']], items[row['child_code']]
                order[parent.id] += 1
                parent.requires_assembly = parent.item_type == 'material'
                line = models.BOMLine(parent_item_id=parent.id, child_item_id=child.id, quantity=row['quantity'],
                                      sort_order=order[parent.id], line_remark=row.get('line_remark'))
                db.add(line); db.flush()
                if row.get('candidates'):
                    count = len(row['candidates'])
                    base, remainder = divmod(10000, count)
                    members = [{'item_id': items[code].id,
                                'market_share': str(Decimal(base + (1 if index < remainder else 0)) / 100)}
                               for index, code in enumerate(row['candidates'])]
                    config = models.PathAlternative(owner_item_id=parent.id, line_path=str(line.id), mode='custom',
                                                    selected_item_id=child.id, members_json=json.dumps(members))
                    db.add(config); db.flush()
                    services.audit(db, actor.id, 'configure', 'path_alternative', config.id,
                                   f"历史临时半成品 {row['x_source']} 转换为直接组成与选配",
                                   after=configuration_dict(db, config))
            for code, record in records.items():
                if record.get('change_note'):
                    services.audit(db, actor.id, 'migrate_change_note', 'item', items[code].id,
                                   record['change_note'], after={'message': '原始变更说明保留'})
            for row in report['zero_quantity_adjustments']:
                services.audit(db, actor.id, 'migrate_quantity', 'item', items[row['parent_code']].id,
                               f"按确认规则将 {row['child_code']} {items[row['child_code']].name} 的原始零数量调整为 1",
                               before={'quantity': '0'}, after={'quantity': '1', 'child_code': row['child_code']})
            for row in report['key_codes_normalized']:
                services.audit(db, actor.id, 'normalize_key_component_code', 'item', items[row['code']].id,
                               '沿用关键器件码规范：移除空白并转大写；原始辅助索引码保留',
                               before={'key_component_code': row['before']}, after={'key_component_code': row['after']})
            for rule in rules:
                db.add(models.CodeRule(**rule))
            services.ensure_default_non_material_code_rules(db)
            db.flush()
            # Exact archive and composition reconciliation before optional demo records.
            assert len(items) == len(records)
            actual = {(line.parent.code, line.child.code): Decimal(line.quantity)
                      for line in db.scalars(select(models.BOMLine))}
            expected = {(r['parent_code'], r['child_code']): r['quantity'] for r in relationships}
            if actual != expected:
                raise ValueError('组成数量对账失败')
            report.update(imported_items=len(items), imported_bom_lines=len(actual),
                          unofficial_codes=sorted(code for code in items if code.startswith('99.')),
                          machine_models=dict(Counter(i.machine_model for i in items.values() if i.item_type == 'machine')))
            db.commit()
            from .demo import DEMO_CODES, seed_demo_in_session
            if demo and not set(DEMO_CODES).intersection(records):
                report['demo'] = seed_demo_in_session(db, actor)
                for line in db.scalars(select(models.BOMLine).where(models.BOMLine.alternative_group_id.is_not(None))):
                    line.alternative_group_id = None
                db.flush()
                db.execute(delete(models.AlternativeMember)); db.execute(delete(models.AlternativeGroup))
            elif demo:
                report['demo'] = {'skipped': '演示保留编码与正式数据冲突，未覆盖正式数据'}
            services.audit(db, actor.id, 'migrate_v1_2', 'database', None, '从最新生产源建立 V1.2 兼容数据库')
            db.commit()
            if demo and not set(DEMO_CODES).intersection(records):
                from .v1_2_demo import seed_in_session
                report['path_demo'] = seed_in_session(db, actor)
            for item in db.scalars(select(models.Item).where(models.Item.item_type == 'machine')):
                item.machine_model = classify_machine_name(item.name)
            for item in db.scalars(select(models.Item).where(models.Item.item_type == 'material', models.Item.status.is_(None))):
                item.status = 'active'
            db.flush()
            EffectiveBOM(db).validate()
            if db.execute(text('PRAGMA foreign_key_check')).all():
                raise ValueError('外键校验失败')
            report['counts'] = dict(Counter(db.scalars(select(models.Item.item_type))))
            db.execute(text('INSERT INTO code_sequences(name,next_value) VALUES (:name,:floor) ON CONFLICT(name) DO UPDATE SET next_value=max(code_sequences.next_value,excluded.next_value)'),
                       {'name': services.UNOFFICIAL_SEQUENCE_NAME, 'floor': services.unofficial_sequence_floor(db)})
            report['next_unofficial_code'] = services.preview_unofficial_code(db)
            report['validated'] = True
            services.audit(db, actor.id, 'production_rebuild', 'database', None, '四次需求：新版生产数据重建并通过对账', after=report)
            db.commit()
        with closing(sqlite3.connect(target)) as conn:
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('数据库完整性校验失败')
        from .production_verify import verify_database
        report['source_reconciliation'] = verify_database(target, source, accounts)
        report['database'] = str(target)
        target.with_suffix('.report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
        return report
    finally:
        engine.dispose()


def activate_database(candidate: Path, target: Path):
    candidate, target = candidate.resolve(), target.resolve()
    if candidate == target or not candidate.is_file():
        raise ValueError('候选数据库无效')
    report_path = candidate.with_suffix('.report.json')
    if not report_path.is_file() or not json.loads(report_path.read_text(encoding='utf-8')).get('validated'):
        raise ValueError('缺少候选库验证报告，不允许替换')
    with closing(sqlite3.connect(candidate, timeout=3)) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('候选库校验失败')
        if not conn.execute("SELECT 1 FROM audit_events WHERE action='production_rebuild'").fetchone():
            raise ValueError('候选库缺少生产重建标记')
        if conn.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
            raise ValueError('候选库正在使用，不能启用')
        if conn.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower() != 'delete':
            raise ValueError('候选库正在使用，不能启用')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = None
    if target.exists():
        settings.backup_dir.mkdir(parents=True, exist_ok=True)
        backup = settings.backup_dir / f'before-production-rebuild-{stamp}.db'
        with closing(sqlite3.connect(target, timeout=3)) as src:
            if src.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('当前库完整性异常，停止替换')
            with closing(sqlite3.connect(backup)) as dst:
                src.backup(dst)
                if dst.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('备份验证失败')
            if src.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0] != 0:
                raise ValueError('数据库正在使用，请先停止服务')
            if src.execute('PRAGMA journal_mode=DELETE').fetchone()[0].lower() != 'delete':
                raise ValueError('无法取得独占数据库访问，请停止服务')
    target.parent.mkdir(parents=True, exist_ok=True)
    os.replace(candidate, target)
    result = {'database': str(target), 'backup': str(backup) if backup else None, 'source_report': str(report_path)}
    settings.report_dir.mkdir(parents=True, exist_ok=True)
    (settings.report_dir / f'production-activation-{stamp}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return result


def main():
    parser = argparse.ArgumentParser(description='先构建并验证独立候选库；停止服务后再明确激活，旧库先备份')
    parser.add_argument('--candidate', type=Path)
    parser.add_argument('--source', type=Path, default=LEGACY_PATH)
    parser.add_argument('--accounts-file', type=Path)
    parser.add_argument('--activate', type=Path)
    parser.add_argument('--target', type=Path, default=PROJECT_ROOT / 'runtime' / 'bom_v1.db')
    args = parser.parse_args()
    if args.activate:
        result = activate_database(args.activate, args.target)
    elif args.candidate:
        result = build_database(args.candidate, load_accounts(args.accounts_file), args.source)
        result = {k: result[k] for k in ('database', 'imported_items', 'imported_bom_lines', 'x_groups_removed', 'counts', 'validated')}
    else:
        parser.error('指定 --candidate 构建，或 --activate 激活候选库')
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))


if __name__ == '__main__':
    main()
