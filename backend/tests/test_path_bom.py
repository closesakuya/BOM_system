from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.app import models, schemas, services
from backend.app.path_bom import EffectiveBOM, save_configuration


def test_inheritance_override_disable_and_ownership(db):
    actor = db.scalar(select(models.User))
    def create(code, kind, children=()):
        return services.create_item(db, schemas.ItemCreate(
            code=code, item_type=kind, name=code, source_type='purchased' if kind=='material' else None,
            status='active', similarity_confirmed=True,
            components=[schemas.BOMComponentIn(child_item_id=c.id, quantity=Decimal(2)) for c in children]), actor)
    a = create('10.7771.0', 'material')
    b = create('10.7772.0', 'material')
    semi = create('05.777.01', 'semi_finished', [a])
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
