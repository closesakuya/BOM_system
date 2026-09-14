from __future__ import annotations
import json
from sqlalchemy import select, text
from fastapi import HTTPException
from . import models


def allocate_id(db, table: str, entity: str):
    if (table, entity) not in {('items','item'),('bom_lines','bom_line')}:
        raise ValueError('invalid sequence')
    # SQLite write lock acquired by upsert; rollback returns reserved ID.
    return db.execute(text(f"""
        INSERT INTO code_sequences(name,next_value)
        VALUES (:name, max((SELECT coalesce(max(id),0) FROM {table}),
          (SELECT coalesce(max(entity_id),0) FROM audit_events WHERE entity_type=:entity))+2)
        ON CONFLICT(name) DO UPDATE SET next_value=max(code_sequences.next_value+1,excluded.next_value)
        RETURNING next_value-1
    """), {'name':'id_'+table,'entity':entity}).scalar_one()


def delete_item(db, item, actor, reason):
    from . import services
    from .path_bom import configuration_dict
    services.ensure_item_writable(item)
    parents = list(db.scalars(select(models.BOMLine).where(models.BOMLine.child_item_id==item.id)))
    refs = [f'{line.parent.code} {line.parent.name}' for line in parents if line.parent_item_id != item.id]
    for config in db.scalars(select(models.PathAlternative)):
        if config.owner_item_id != item.id and (config.selected_item_id==item.id or any(int(m['item_id'])==item.id for m in json.loads(config.members_json))):
            owner=db.get(models.Item,config.owner_item_id)
            refs.append(f'{owner.code} {owner.name} 的路径选配：{configuration_dict(db,config)["path_label"]}')
    if refs:
        raise HTTPException(409, '不能删除，仍被引用：'+'；'.join(dict.fromkeys(refs)))
    before=services.item_dict(item)
    # Ensure IDs used by prior audit/path records are never recycled.
    allocate_id(db,'items','item')
    allocate_id(db,'bom_lines','bom_line')
    for link in db.scalars(select(models.MaterialPromotionLink).where(models.MaterialPromotionLink.target_item_id==item.id)):
        db.add(models.DeletedMaterialPromotion(source_item_id=link.source_item_id,target_item_id=item.id,
                                              target_code=item.code,target_name=item.name))
        db.delete(link)
    for copied in db.scalars(select(models.Item).where(models.Item.copied_from_id==item.id)):
        copied.copied_from_id=None
    for config in db.scalars(select(models.PathAlternative).where(models.PathAlternative.owner_item_id==item.id)):
        services.audit(db,actor.id,'delete','path_alternative',config.id,reason,before=configuration_dict(db,config))
        db.delete(config)
    for line in db.scalars(select(models.BOMLine).where(models.BOMLine.parent_item_id==item.id)):
        services.audit(db,actor.id,'delete','bom_line',line.id,reason,before=services.bom_line_dict(line))
        db.delete(line)
    db.flush()
    services.audit(db,actor.id,'delete','item',item.id,reason,before=before)
    db.delete(item)
    db.commit()


def clear_line_configurations(db, line_id, actor, reason, confirmed=False):
    from .services import audit
    from .path_bom import configuration_dict
    line_ids = {str(v) for v in line_id} if isinstance(line_id,list) else {str(line_id)}
    affected=[c for c in db.scalars(select(models.PathAlternative)) if line_ids.intersection(c.line_path.split('/'))]
    if affected and not confirmed:
        raise HTTPException(409, {'message':'此组成变更会清除以下路径选配，请确认',
                                 'affected_configurations':[configuration_dict(db,c) for c in affected]})
    for c in affected:
        audit(db,actor.id,'delete','path_alternative',c.id,reason,before=configuration_dict(db,c))
        db.delete(c)
    db.flush()


def copy_configurations(db, source_id, target_id):
    old=list(db.scalars(select(models.BOMLine).where(models.BOMLine.parent_item_id==source_id)))
    new=list(db.scalars(select(models.BOMLine).where(models.BOMLine.parent_item_id==target_id)))
    mapping={a.id:b.id for a in old for b in new if a.child_item_id==b.child_item_id}
    for config in db.scalars(select(models.PathAlternative).where(models.PathAlternative.owner_item_id==source_id)):
        path=[int(v) for v in config.line_path.split('/')]
        if path[0] not in mapping:
            continue
        for member_id in {config.selected_item_id,*[int(m['item_id']) for m in json.loads(config.members_json)]}:
            member=db.get(models.Item,member_id)
            if not member or member.deleted_at or member.status=='disabled' or not member.is_formally_imported:
                raise HTTPException(409,'复制来源的专属选配含无效或停用候选，请先修正来源配置')
        path[0]=mapping[path[0]]
        db.add(models.PathAlternative(owner_item_id=target_id,line_path='/'.join(map(str,path)),
              mode=config.mode,selected_item_id=config.selected_item_id,members_json=config.members_json))
    db.flush()
