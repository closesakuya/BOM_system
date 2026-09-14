from __future__ import annotations
import json
from sqlalchemy import select
from . import models, services
from .database import SessionLocal
from .path_bom import EffectiveBOM, path_key, configuration_dict


def seed_in_session(db, actor):
    if db.scalar(select(models.AuditEvent.id).where(models.AuditEvent.action=='seed_v1_2_demo').limit(1)):
        return {'version':'1.2','created_configurations':[], 'already_initialized':True}
    items={i.code:i for i in db.scalars(select(models.Item).where(models.Item.code.in_(
        ['05.999.01','05.999.02','05.999.03','05.999.05','03.999.01','03.999.04','00.999.01','00.999.02','00.999.03',
         '90.9004.01','90.9005.01','90.9006.01','90.9007.01','90.9008.01','90.9009.01'])))}
    if len(items)!=15:
        raise RuntimeError('缺少基础演示物料，请先初始化完整演示档案')
    created=[]
    def configure(owner_code, child_code, alternate_code, mode='custom', chosen=None):
        graph=EffectiveBOM(db)
        owner=items[owner_code]
        row=next((r for r in graph.rows(owner.id) if r['item']['code']==child_code),None)
        if row is None:raise RuntimeError(f'演示路径不存在：{owner_code} → {child_code}')
        key=path_key(row['line_path'])
        if (owner.id,key) in graph.configs:return
        a,b=items[child_code],items[alternate_code]
        config=models.PathAlternative(owner_item_id=owner.id,line_path=key,mode=mode,
            selected_item_id=items[chosen or child_code].id,
            members_json=json.dumps([{'item_id':a.id,'market_share':'60.00'},{'item_id':b.id,'market_share':'40.00'}] if mode=='custom' else []))
        db.add(config);db.flush()
        services.audit(db,actor.id,'configure','path_alternative',config.id,'V1.2 虚拟路径选配示例',after=configuration_dict(db,config))
        created.append({'owner':owner_code,'child':child_code,'mode':mode})
    for entry in [('05.999.01','90.9004.01','90.9005.01'),('05.999.02','90.9006.01','90.9007.01'),
                  ('05.999.03','90.9008.01','90.9009.01'),('03.999.01','05.999.01','05.999.05'),
                  ('00.999.01','03.999.01','03.999.04')]:configure(*entry)
    configure('00.999.02','90.9004.01','90.9005.01',chosen='90.9005.01')
    configure('00.999.03','90.9006.01','90.9007.01',mode='disabled')
    EffectiveBOM(db).validate()
    services.audit(db,actor.id,'seed_v1_2_demo','database',None,'V1.2 路径选配示例初始化完成',after={'configurations':created})
    db.commit()
    return {'version':'1.2','created_configurations':created}


if __name__=='__main__':
    with SessionLocal() as db:
        actor=db.scalar(select(models.User).where(models.User.role=='admin'))
        print(json.dumps(seed_in_session(db,actor),ensure_ascii=False,indent=2))
