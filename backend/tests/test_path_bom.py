from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app import models, schemas, services
from backend.app.path_bom import EffectiveBOM, save_configuration


@pytest.mark.parametrize('owner_kind', ['semi_finished', 'material'])
def test_inheritance_override_disable_and_ownership(db, owner_kind):
    actor = db.scalar(select(models.User))
    def create(code, kind, children=()):
        return services.create_item(db, schemas.ItemCreate(
            code=code, item_type=kind, name=code, source_type='purchased' if kind=='material' else None,
            status='active', similarity_confirmed=True,
            components=[schemas.BOMComponentIn(child_item_id=c.id, quantity=Decimal(2)) for c in children]), actor)
    a = create('10.7771.0', 'material')
    b = create('10.7772.0', 'material')
    semi = create('10.7773.0' if owner_kind == 'material' else '05.777.01', owner_kind, [a])
    y = create('00.777.01', 'machine', [semi])
    d = create('00.778.01', 'machine', [semi])
    y.machine_model, d.machine_model = 'Y60', 'D60'
    db.commit()
    line = EffectiveBOM(db).rows(semi.id)[0]['line_path']
    members = [{'item_id': a.id, 'market_share': '60'}, {'item_id': b.id, 'market_share': '40'}]
    save_configuration(db, semi.id, {'line_path': line, 'mode': 'custom', 'selected_item_id': a.id,
                                     'members': members, 'reason': '下级选配'}, actor)
    y_path = EffectiveBOM(db).rows(y.id)[1]['line_path']
    save_configuration(db, y.id, {'line_path': y_path, 'mode': 'custom', 'selected_item_id': b.id,
                                  'members': members, 'reason': '整机覆盖'}, actor)
    assert services.production_bom(db, y.id)[0]['item']['id'] == b.id
    assert services.production_bom(db, d.id)[0]['item']['id'] == a.id
    assert Decimal(services.production_bom(db, y.id)[0]['quantity']) == 4
    refs = services.model_references_for_items(db, [a.id, b.id])
    assert refs[b.id]['current'] == ['Y60']
    assert refs[a.id]['current'] == ['D60']
    save_configuration(db, y.id, {'line_path': y_path, 'mode': 'disabled', 'selected_item_id': a.id,
                                  'reason': '固定使用'}, actor)
    assert not any(r['is_backup_path'] for r in EffectiveBOM(db).rows(y.id, show_alternatives=True))
    save_configuration(db, y.id, {'line_path': y_path, 'mode': 'inherit', 'reason': '恢复继承'}, actor)
    assert len(services.production_bom(db, y.id, show_alternatives=True)) == 2


def test_purchased_material_expansion_uses_actual_components(db):
    actor = db.scalar(select(models.User))
    a = services.create_item(db, schemas.ItemCreate(item_type='material', code='10.8881.0',
                             name='零件', source_type='purchased', similarity_confirmed=True), actor)
    b = services.create_item(db, schemas.ItemCreate(item_type='material', code='10.8882.0',
                             name='外购组合', source_type='purchased', similarity_confirmed=True,
                             components=[schemas.BOMComponentIn(child_item_id=a.id, quantity=Decimal(3))]), actor)
    assert services.production_bom(db, b.id, expand_materials=False)[0]['item']['id'] == b.id
    assert services.production_bom(db, b.id, expand_materials=True)[0]['item']['id'] == a.id


@pytest.mark.parametrize('select_backup', [False, True])
@pytest.mark.parametrize('owner_kind', ['semi_finished', 'material'])
def test_remove_last_alternative_keeps_selected_and_quantity(db, select_backup, owner_kind):
    actor = db.scalar(select(models.User))
    def create(code, kind, children=()):
        return services.create_item(db, schemas.ItemCreate(code=code, item_type=kind, name=code,
            source_type='purchased' if kind == 'material' else None, similarity_confirmed=True,
            components=[schemas.BOMComponentIn(child_item_id=c.id, quantity=Decimal(3)) for c in children]), actor)
    a = create('10.8871.0', 'material')
    b = create('10.8872.0', 'material')
    semi = create('10.8873.0' if owner_kind == 'material' else '05.887.01', owner_kind, [a])
    machine = create('00.887.01', 'machine', [semi])
    path = EffectiveBOM(db).rows(semi.id)[0]['line_path']
    chosen = b if select_backup else a
    save_configuration(db, semi.id, dict(line_path=path, mode='custom', selected_item_id=chosen.id,
        members=[dict(item_id=a.id, market_share='50'), dict(item_id=b.id, market_share='50')], reason='创建选配'), actor)
    save_configuration(db, semi.id, dict(line_path=path, mode='custom', selected_item_id=chosen.id,
        members=[dict(item_id=chosen.id, market_share='100')], reason='移除最后备选'), actor)
    rows = EffectiveBOM(db).rows(semi.id, show_alternatives=True)
    assert len(rows) == 1 and rows[0]['item']['id'] == chosen.id
    assert rows[0]['configuration_owner'] is None and not rows[0]['members']
    assert Decimal(rows[0]['quantity']) == 3
    assert db.get(models.BOMLine, path[0]).child_item_id == chosen.id
    assert len(EffectiveBOM(db).rows(machine.id, show_alternatives=True)) == 2
    assert Decimal(services.production_bom(db, machine.id)[0]['quantity']) == 9
    assert db.scalar(select(models.AuditEvent).where(models.AuditEvent.reason == '移除最后备选'))


@pytest.mark.parametrize('owner_kind', ['semi_finished', 'material'])
def test_remove_inherited_alternatives_does_not_change_shared_child(db, owner_kind):
    actor = db.scalar(select(models.User))
    def create(code, kind, children=()):
        return services.create_item(db, schemas.ItemCreate(code=code, item_type=kind, name=code,
            source_type='purchased' if kind == 'material' else None, similarity_confirmed=True,
            components=[schemas.BOMComponentIn(child_item_id=c.id, quantity=Decimal(2)) for c in children]), actor)
    a = create('10.8861.0', 'material'); b = create('10.8862.0', 'material')
    semi = create('10.8863.0' if owner_kind == 'material' else '05.886.01', owner_kind, [a])
    machine = create('00.886.01', 'machine', [semi])
    other = create('00.886.02', 'machine', [semi])
    path = EffectiveBOM(db).rows(semi.id)[0]['line_path']
    save_configuration(db, semi.id, dict(line_path=path, mode='custom', selected_item_id=b.id,
        members=[dict(item_id=a.id, market_share='50'), dict(item_id=b.id, market_share='50')], reason='下级选配'), actor)
    nested = EffectiveBOM(db).rows(machine.id)[1]['line_path']
    save_configuration(db, machine.id, dict(line_path=nested, mode='custom', selected_item_id=b.id,
        members=[dict(item_id=b.id, market_share='100')], reason='本机移除备选'), actor)
    rows = EffectiveBOM(db).rows(machine.id, show_alternatives=True)
    assert len(rows) == 2 and rows[1]['item']['id'] == b.id
    assert rows[1]['configuration_mode'] == 'disabled' and not rows[1]['members']
    assert len(EffectiveBOM(db).rows(other.id, show_alternatives=True)) == 3
    assert db.get(models.BOMLine, path[0]).child_item_id == a.id
