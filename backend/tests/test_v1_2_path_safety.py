from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from backend.app import models, schemas, services
from backend.app.path_bom import EffectiveBOM, save_configuration
from backend.app.item_lifecycle import clear_line_configurations, copy_configurations


def test_path_copy_remap_and_clear_requires_confirmation(db):
    actor=db.scalar(select(models.User))
    def create(code,kind,children=()):
        return services.create_item(db,schemas.ItemCreate(code=code,item_type=kind,name=code,
            source_type='purchased' if kind=='material' else None,similarity_confirmed=True,
            components=[schemas.BOMComponentIn(child_item_id=i.id,quantity=Decimal(3)) for i in children]),actor)
    a=create('10.9911.0','material'); b=create('10.9912.0','material')
    semi=create('05.991.01','semi_finished',[a]); root=create('00.991.01','machine',[semi])
    members=[{'item_id':a.id,'market_share':'50'},{'item_id':b.id,'market_share':'50'}]
    path=EffectiveBOM(db).rows(semi.id)[0]['line_path']
    save_configuration(db,semi.id,dict(line_path=path,mode='custom',selected_item_id=b.id,members=members,reason='选配'),actor)
    copy=create('05.992.01','semi_finished',[a]); copy_configurations(db,semi.id,copy.id); db.commit()
    copied=EffectiveBOM(db).rows(copy.id)[0]
    assert copied['item']['id']==b.id and copied['line_path']!=path
    assert Decimal(copied['quantity'])==3
    root_path=EffectiveBOM(db).rows(root.id)[1]['line_path']
    save_configuration(db,root.id,dict(line_path=root_path,mode='disabled',selected_item_id=a.id,reason='上级固定'),actor)
    with pytest.raises(HTTPException) as error:
        clear_line_configurations(db,path[0],actor,'删除组成')
    assert len(error.value.detail['affected_configurations'])==2
    assert len(list(db.scalars(select(models.PathAlternative))))==3
    clear_line_configurations(db,path[0],actor,'确认清除',True)
    assert len(list(db.scalars(select(models.PathAlternative))))==1
    assert EffectiveBOM(db).rows(copy.id)[0]['item']['id']==b.id


def test_history_follows_root_specific_selected_item(client,headers,db):
    actor=db.scalar(select(models.User))
    def create(code,kind,children=()):
        return services.create_item(db,schemas.ItemCreate(code=code,item_type=kind,name=code,source_type='purchased' if kind=='material' else None,similarity_confirmed=True,
            components=[schemas.BOMComponentIn(child_item_id=i.id,quantity=Decimal(1)) for i in children]),actor)
    a=create('10.9511.0','material');b=create('10.9512.0','material')
    semi=create('05.951.01','semi_finished',[a]);y=create('00.951.01','machine',[semi]);d=create('00.952.01','machine',[semi])
    path=EffectiveBOM(db).rows(y.id)[1]['line_path']
    save_configuration(db,y.id,dict(line_path=path,mode='custom',selected_item_id=b.id,
        members=[{'item_id':a.id,'market_share':'50'},{'item_id':b.id,'market_share':'50'}],reason='Y 专属选择'),actor)
    services.update_item(db,b,schemas.ItemUpdate(specification='B 新规格',reason='选中子项 B 档案修改',similarity_confirmed=True),actor)
    services.update_item(db,a,schemas.ItemUpdate(specification='A 新规格',reason='基础子项 A 档案修改',similarity_confirmed=True),actor)
    y_history=client.get(f'/api/items/{y.id}/history',headers=headers).json()
    d_history=client.get(f'/api/items/{d.id}/history',headers=headers).json()
    assert any(e['reason']=='选中子项 B 档案修改' for e in y_history)
    assert not any(e['reason']=='基础子项 A 档案修改' for e in y_history)
    assert not any(e['reason']=='选中子项 B 档案修改' for e in d_history)
    assert any(e['reason']=='基础子项 A 档案修改' for e in d_history)


def test_duplicate_cycle_and_invalid_shares_are_atomic(db):
    actor=db.scalar(select(models.User))
    def make(code,children=()):
        return services.create_item(db,schemas.ItemCreate(code=code,item_type='semi_finished',name=code,similarity_confirmed=True,
            components=[schemas.BOMComponentIn(child_item_id=i.id,quantity=Decimal(1)) for i in children]),actor)
    a=make('05.981.01'); b=make('05.982.01'); root=make('05.983.01',[a,b])
    path=EffectiveBOM(db).rows(root.id)[0]['line_path']
    def configure(second,shares=('50','50')):
        return save_configuration(db,root.id,dict(line_path=path,mode='custom',selected_item_id=a.id,
            members=[{'item_id':a.id,'market_share':shares[0]},{'item_id':second.id,'market_share':shares[1]}],reason='错误操作'),actor)
    for other,shares in [(b,('50','50')),(root,('50','50')),(b,('20','20'))]:
        with pytest.raises(HTTPException):configure(other,shares)
        assert not list(db.scalars(select(models.PathAlternative)))
        assert [r['item']['id'] for r in EffectiveBOM(db).rows(root.id)]==[a.id,b.id]


def test_lower_configuration_change_checks_ancestor_effective_siblings(db):
    actor=db.scalar(select(models.User))
    def make(code,kind,children=()):
        return services.create_item(db,schemas.ItemCreate(code=code,item_type=kind,name=code,source_type='purchased' if kind=='material' else None,similarity_confirmed=True,
            components=[schemas.BOMComponentIn(child_item_id=i.id,quantity=Decimal(1)) for i in children]),actor)
    a=make('10.9711.0','material');b=make('10.9712.0','material');c=make('10.9713.0','material')
    semi=make('05.974.01','semi_finished',[a,b]);root=make('00.974.01','machine',[semi])
    root_path=next(r['line_path'] for r in EffectiveBOM(db).rows(root.id) if r['item']['id']==b.id)
    save_configuration(db,root.id,dict(line_path=root_path,mode='custom',selected_item_id=c.id,
        members=[{'item_id':b.id,'market_share':'50'},{'item_id':c.id,'market_share':'50'}],reason='上级第二行专属选择'),actor)
    source_path=EffectiveBOM(db).rows(semi.id)[0]['line_path']
    with pytest.raises(HTTPException,match='同一父项实际选用重复'):
        save_configuration(db,semi.id,dict(line_path=source_path,mode='custom',selected_item_id=c.id,
            members=[{'item_id':a.id,'market_share':'50'},{'item_id':c.id,'market_share':'50'}],reason='下级切换会造成上级冲突'),actor)
    assert EffectiveBOM(db).rows(semi.id)[0]['item']['id']==a.id
    assert len(list(db.scalars(select(models.PathAlternative))))==1
