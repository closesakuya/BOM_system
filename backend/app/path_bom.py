from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import models


def path_key(path: list[int]) -> str:
    return "/".join(str(value) for value in path)


class EffectiveBOM:
    """One consistent resolver for actual/backup paths, inheritance and validation."""

    def __init__(self, db: Session):
        self.db = db
        self.items = {item.id: item for item in db.scalars(select(models.Item))}
        self.lines: dict[int, list[models.BOMLine]] = defaultdict(list)
        for line in db.scalars(select(models.BOMLine).order_by(models.BOMLine.sort_order, models.BOMLine.id)):
            self.lines[line.parent_item_id].append(line)
        self.configs = {(row.owner_item_id, row.line_path): row for row in db.scalars(select(models.PathAlternative))}
        self.serialized: dict[int, dict[str, Any]] = {}

    def item_value(self, item):
        from .services import item_dict
        if item.id not in self.serialized:
            self.serialized[item.id] = item_dict(item)
        return self.serialized[item.id].copy()

    def potential_ancestors(self, item_id: int):
        reverse = defaultdict(set)
        for parent, lines in self.lines.items():
            for line in lines: reverse[line.child_item_id].add(parent)
        for config in self.configs.values():
            for child in {config.selected_item_id, *[int(m['item_id']) for m in json.loads(config.members_json)]}:
                reverse[child].add(config.owner_item_id)
        pending=[item_id]; found=set()
        while pending:
            for parent in reverse[pending.pop()]:
                if parent not in found:found.add(parent);pending.append(parent)
        return found

    def resolve(self, ancestors: list[int], line_path: list[int]):
        # Root-most override takes precedence; absent local records mean inherit.
        for offset, owner in enumerate(ancestors):
            config = self.configs.get((owner, path_key(line_path[offset:])))
            if config:
                return config
        return None

    def rows(self, root_id: int, *, show_alternatives: bool = False,
             expand_materials: bool = True, max_depth: int = 50, max_nodes: int = 20000):
        from .services import item_dict
        if root_id not in self.items:
            raise HTTPException(404, "物料不存在")
        output: list[dict[str, Any]] = []

        def walk(ancestors: list[int], line_path: list[int], multiplier: Decimal, backup: bool,
                 inherited_share: str | None = None, inherited_name: str | None = None):
            parent_id = ancestors[-1]
            siblings = self.lines.get(parent_id, [])
            chosen: set[int] = set()
            resolved = []
            for line in siblings:
                position = [*line_path, line.id]
                config = self.resolve(ancestors, position)
                selected = config.selected_item_id if config else line.child_item_id
                if selected in chosen:
                    names = " → ".join(f"{self.items[i].code} {self.items[i].name}" for i in ancestors)
                    raise HTTPException(409, f"同一父项实际选用重复：{names} → {self.items[selected].code}")
                chosen.add(selected)
                resolved.append((line, position, config, selected))
            for line, position, config, selected in resolved:
                members = json.loads(config.members_json) if config and config.mode == "custom" else []
                candidates = [selected]
                if show_alternatives:
                    candidates += [int(m['item_id']) for m in members if int(m['item_id']) != selected]
                for child_id in candidates:
                    child = self.items.get(child_id)
                    if not child or child.deleted_at:
                        raise HTTPException(409, "BOM 路径包含已删除或不存在的物料")
                    if child_id in ancestors:
                        names = " → ".join(f"{self.items[i].code} {self.items[i].name}" for i in [*ancestors, child_id])
                        raise HTTPException(409, f"选配或 BOM 存在环路：{names}")
                    if len(ancestors) > max_depth or len(output) >= max_nodes:
                        raise HTTPException(409, "BOM 展开超过安全上限（50 层或 20000 节点）")
                    is_backup = backup or child_id != selected
                    share = next((str(m['market_share']) for m in members if int(m['item_id']) == child_id), inherited_share)
                    owner = self.items.get(config.owner_item_id) if config else None
                    name = f"{owner.code} 路径选配" if owner else inherited_name
                    total = multiplier * Decimal(line.quantity)
                    path = [*ancestors, child_id]
                    child_lines = self.lines.get(child_id, [])
                    stopped = child.item_type == "material" and not expand_materials
                    output.append({
                        'sequence': len(output) + 1, 'level': len(ancestors), 'path': path,
                        'line_path': position, 'parent_item_id': parent_id, 'line_id': line.id,
                        'base_child_item_id': line.child_item_id, 'quantity': str(line.quantity),
                        'total_quantity': str(total), 'line_remark': line.line_remark,
                        'item': self.item_value(child), 'disabled_warning': child.status == 'disabled',
                        'is_alternative': is_backup, 'is_backup_path': is_backup,
                        'alternative_group_id': config.id if config else None,
                        'alternative_group_name': name, 'market_share': share,
                        'configuration_mode': config.mode if config else 'inherit',
                        'configuration_owner': self.item_value(owner) if owner else None,
                        'local_configuration': bool(config and config.owner_item_id == root_id),
                        'members': [{**m, 'item': self.item_value(self.items[int(m['item_id'])])} for m in members],
                        'is_terminal_material': child.item_type == 'material' and (not child_lines or stopped),
                    })
                    if not stopped:
                        walk(path, position, total, is_backup, share, name)

        walk([root_id], [], Decimal(1), False)
        return output

    def validate(self, changed_roots=None):
        # Cached graph makes checks consistent without one SQL query per tree node.
        roots=set(self.items) if changed_roots is None else set(changed_roots)
        if changed_roots is not None:
            for root_id in changed_roots:roots.update(self.potential_ancestors(root_id))
        for root in (self.items[i] for i in roots):
            if root.deleted_at or root.unofficial_status == 'archived':
                continue
            self.rows(root.id, show_alternatives=True)


def configuration_dict(db: Session, row: models.PathAlternative):
    from .services import item_dict
    owner = db.get(models.Item, row.owner_item_id)
    members = json.loads(row.members_json)
    path_ids=[int(v) for v in row.line_path.split('/')]
    descriptions=[]
    for line_id in path_ids:
        line=db.get(models.BOMLine,line_id)
        if line:descriptions.append(f'{line.child.code} {line.child.name}')
    return {'id': row.id, 'owner': item_dict(owner), 'line_path': path_ids,
            'path_label':' → '.join(descriptions), 'selected_item':item_dict(db.get(models.Item,row.selected_item_id)),
            'mode': row.mode, 'selected_item_id': row.selected_item_id,
            'members': [{**member, 'item': item_dict(db.get(models.Item, int(member['item_id'])))} for member in members]}


def save_configuration(db: Session, owner_id: int, payload: dict, actor: models.User):
    from . import services
    owner = db.get(models.Item, owner_id)
    if not owner or owner.deleted_at:
        raise HTTPException(404, '所属物料不存在')
    services.ensure_item_writable(owner)
    if owner.item_type not in {'semi_finished', 'unit', 'machine'}:
        raise HTTPException(422, '只能在半成品、单元和整机中配置选配')
    reason = str(payload.get('reason', '')).strip()
    if not reason:
        raise HTTPException(422, '请填写变更说明')
    path = payload.get('line_path', [])
    if not path or any(type(v) is not int or v <= 0 for v in path):
        raise HTTPException(422, '请选择有效 BOM 路径')
    graph = EffectiveBOM(db)
    target = next((r for r in graph.rows(owner_id) if r['line_path'] == path), None)
    if not target:
        raise HTTPException(409, '该路径已变化，请刷新后重新选择')
    if graph.items[target['parent_item_id']].item_type == 'material':
        raise HTTPException(422, '原材料下级不支持选配配置')
    mode = payload.get('mode', 'custom')
    if mode not in {'inherit', 'custom', 'disabled'}:
        raise HTTPException(422, '选配模式不正确')
    key = path_key(path)
    old = graph.configs.get((owner_id, key))
    before = configuration_dict(db, old) if old else None
    try:
        selected = int(payload.get('selected_item_id') or target['item']['id'])
        members = payload.get('members', []) if mode == 'custom' else []
        ids = [int(m['item_id']) for m in members]
    except (TypeError,ValueError,KeyError):
        raise HTTPException(422,'选配候选或当前项格式不正确')
    # A single remaining selected component means remove alternatives, not an
    # invalid group. Keep deep overrides fixed without changing shared children.
    single_selected = mode == 'custom' and ids == [selected]
    if single_selected:
        mode, members = 'disabled', []
    if mode == 'custom':
        if len(ids) < 2 or len(ids) != len(set(ids)) or selected not in ids:
            raise HTTPException(422, '自定义选配至少包含两个不同组件，当前项必须在候选内')
        try:
            shares = [Decimal(str(m['market_share'])) for m in members]
            valid = all(s.is_finite() and 0 <= s <= 100 and s == s.quantize(Decimal('.01')) for s in shares)
        except Exception:
            valid = False
        if not valid or sum(shares) != Decimal(100):
            raise HTTPException(422, '市场占比须保留至多两位小数，合计 100%')
        members = [{'item_id': i, 'market_share': str(s)} for i, s in zip(ids, shares)]
    if mode != 'inherit':
        for item_id in set([selected, *ids]):
            child = graph.items.get(item_id)
            if not child or child.deleted_at or child.status == 'disabled' or not child.is_formally_imported or child.unofficial_status == 'archived':
                raise HTTPException(409, '候选必须是正式、未停用的有效物料')
            if child.item_type != target['item']['item_type']:
                raise HTTPException(409, '选配组件必须与原组件类型相同')
            siblings = [r for r in graph.rows(owner_id) if r['line_path'][:-1] == path[:-1] and r['line_path'] != path]
            if any(r['item']['id'] == item_id for r in siblings):
                raise HTTPException(409, f"该父项已直接包含 {child.code}，不能重复或合并")
    with db.begin_nested():
        if single_selected and len(path) == 1:
            line = db.get(models.BOMLine, path[0])
            if line.child_item_id != selected:
                line_before = services.bom_line_dict(line)
                line.child_item_id = selected
                line.child = graph.items[selected]
                services.audit(db, actor.id, 'update', 'bom_line', line.id, reason,
                               before=line_before, after=services.bom_line_dict(line))
            if old:
                db.delete(old)
        elif mode == 'inherit':
            if old:
                db.delete(old)
        elif old:
            old.mode, old.selected_item_id, old.members_json = mode, selected, json.dumps(members)
        else:
            db.add(models.PathAlternative(owner_item_id=owner_id, line_path=key, mode=mode,
                                         selected_item_id=selected, members_json=json.dumps(members)))
        db.flush()
        # If a selected ancestor changes, descendant overrides must be explicitly discarded.
        new_graph = EffectiveBOM(db)
        invalid = []
        for config in new_graph.configs.values():
            rows = new_graph.rows(config.owner_item_id)
            if not any(path_key(r['line_path']) == config.line_path for r in rows):
                invalid.append(config)
        if invalid and not payload.get('confirm_clear'):
            raise HTTPException(409, {'message': '切换将清除失效的路径配置，请确认',
                                      'affected_configurations': [configuration_dict(db, c) for c in invalid]})
        for config in invalid:
            services.audit(db, actor.id, 'delete', 'path_alternative', config.id, reason,
                           before=configuration_dict(db, config))
            db.delete(config)
        db.flush()
        EffectiveBOM(db).validate([owner_id])
        saved=db.scalar(select(models.PathAlternative).where(models.PathAlternative.owner_item_id==owner_id,models.PathAlternative.line_path==key))
        services.audit(db, actor.id, 'configure', 'path_alternative', old.id if old else None, reason,
                       before, configuration_dict(db,saved) if saved else {'owner_item_id':owner_id,'mode':'inherit','line_path':path})
    db.commit()
    return {'saved': True}


def production_rows(db: Session, root_id: int, **options):
    from .services import item_dict
    graph = EffectiveBOM(db)
    root = graph.items.get(root_id)
    rows = graph.rows(root_id, **options)
    if root and root.item_type == 'material' and (not graph.lines.get(root_id) or options.get('expand_materials') is False):
        return [{'sequence':1,'item': item_dict(root), 'quantity': '1', 'paths': [[root_id]], 'is_backup_path': False}]
    merged = {}
    backups = []
    for row in rows:
        if not row['is_terminal_material']:
            continue
        if row['is_backup_path']:
            backups.append({**row, 'quantity': format(Decimal(row['total_quantity']).normalize(),'f'), 'paths': [row['path']]})
        else:
            target = merged.setdefault(row['item']['id'], {**row, 'quantity': Decimal(0), 'paths': []})
            target['quantity'] += Decimal(row['total_quantity'])
            target['paths'].append(row['path'])
    result=[{**r, 'quantity': format(r['quantity'].normalize(), 'f')} for r in merged.values()] + backups
    return [{**r, 'sequence': index} for index,r in enumerate(result,1)]
