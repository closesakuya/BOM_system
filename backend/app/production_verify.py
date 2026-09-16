"""Read-only reconciliation of a rebuilt database against the approved source transforms."""
from __future__ import annotations

import argparse
import json
import sqlite3
from contextlib import closing
from decimal import Decimal
from pathlib import Path

from . import auth, services
from .demo import DEMO_CODES
from .machine_model_backfill import classify_machine_name
from .migration import LEGACY_PATH, read_legacy
from .production_rebuild import transform_source, load_accounts


def verify_database(database: Path, source: Path = LEGACY_PATH, accounts=None):
    records, rows, _ = read_legacy(source)
    records, rows, conversion = transform_source(records, rows)
    with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        items = {row['code']: dict(row) for row in conn.execute('SELECT * FROM items')}
        missing = set(records) - set(items)
        unexpected = set(items) - set(records) - set(DEMO_CODES)
        if missing or unexpected:
            raise ValueError(f'档案编码差异：缺少 {sorted(missing)}；意外新增 {sorted(unexpected)}')
        fields = ('item_type', 'auxiliary_code', 'name', 'specification', 'source_type', 'unit',
                  'remark', 'previous_version_name', 'invoice_name', 'material_attribute')
        differences = [(code, field) for code, row in records.items() for field in fields
                       if row[field] != items[code][field]]
        if differences:
            raise ValueError(f'档案字段差异：{differences[:10]}')
        for code, row in records.items():
            item = items[code]
            if row['item_type'] == 'material' and item['key_component_code'] != services.normalize_key_component_code(row['auxiliary_code']):
                raise ValueError(f'{code} 关键器件码不符')
            if bool(item['is_formally_imported']) == code.startswith('99.'):
                raise ValueError(f'{code} 正式状态不符')
            if row['item_type'] == 'machine' and item['machine_model'] != classify_machine_name(row['name']):
                raise ValueError(f'{code} 机型不符')
        actual = {(r['parent'], r['child']): Decimal(str(r['quantity'])) for r in conn.execute(
            'SELECT p.code parent,c.code child,l.quantity FROM bom_lines l JOIN items p ON p.id=l.parent_item_id JOIN items c ON c.id=l.child_item_id')
            if r['parent'] in records}
        expected = {(r['parent_code'], r['child_code']): r['quantity'] for r in rows}
        if actual != expected:
            raise ValueError('直接组成或数量与源转换结果不符')
        by_id = {row['id']: row for row in items.values()}
        configs = {}
        for config in conn.execute('SELECT * FROM path_alternatives'):
            owner = by_id[config['owner_item_id']]['code']
            if owner in records:
                configs[owner, by_id[config['selected_item_id']]['code']] = dict(config)
        if len(configs) != len(conversion['converted_positions']):
            raise ValueError('X 组选配配置数量不符')
        for row in conversion['converted_positions']:
            config = configs[row['parent'], row['selected']]
            members = json.loads(config['members_json'])
            if [by_id[m['item_id']]['code'] for m in members] != row['candidates']:
                raise ValueError(f"选配成员/默认顺序不符：{row['parent']}")
            base, remainder = divmod(10000, len(members))
            if any(Decimal(m['market_share']) != Decimal(base + (1 if i < remainder else 0)) / 100 for i, m in enumerate(members)):
                raise ValueError('选配平均占比不符')
        if accounts is not None:
            users = list(conn.execute('SELECT username,role,password_hash FROM users'))
            if len(users) != 4 or any(u['username'] not in accounts or u['role'] != u['username'] or
                                     not auth.verify_password(accounts[u['username']], u['password_hash']) for u in users):
                raise ValueError('初始化账户校验失败')
        next_value = conn.execute('SELECT next_value FROM code_sequences WHERE name=?', (services.UNOFFICIAL_SEQUENCE_NAME,)).fetchone()[0]
        expected_next = max(((int(code[3:7]) - 1) * 10 + int(code[-1]) for code in items if code.startswith('99.')), default=-1) + 1
        if next_value < expected_next:
            raise ValueError('未正式编号游标落后于已有编码')
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('SQLite 完整性验证失败')
        return {'passed': True, 'database': str(database.resolve()), 'archives_compared': len(records),
                'archive_differences': 0, 'compositions_compared': len(expected), 'x_configurations': len(configs),
                'zero_quantity_adjustments': len(conversion['zero_quantity_adjustments']),
                'next_unofficial_code': services.unofficial_code_from_sequence(next_value),
                'accounts_verified': accounts is not None}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--source', type=Path, default=LEGACY_PATH)
    parser.add_argument('--accounts-file', type=Path)
    args = parser.parse_args()
    result = verify_database(args.database, args.source, load_accounts(args.accounts_file) if args.accounts_file else None)
    args.database.with_suffix('.verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))
