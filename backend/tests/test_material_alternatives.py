from decimal import Decimal

from sqlalchemy import select

from backend.app import models, schemas, services
from backend.app.path_bom import EffectiveBOM


def test_material_options_api_safety_and_nested_quantities(client, headers, db):
    actor = db.scalar(select(models.User))

    def make(code, children=()):
        return services.create_item(db, schemas.ItemCreate(
            code=code, item_type='material', name=code, source_type='purchased',
            similarity_confirmed=True,
            components=[schemas.BOMComponentIn(child_item_id=c.id, quantity=Decimal(3))
                        for c in children]), actor)

    a = make('10.8851.0')
    b = make('10.8852.0')
    sibling = make('10.8853.0')
    assembly = make('10.8854.0', [a, sibling])
    root = make('10.8855.0', [assembly])
    path = EffectiveBOM(db).rows(assembly.id)[0]['line_path']

    def configure(owner, line_path, candidate, selected=None, reason='原材料选配'):
        return client.put(f'/api/items/{owner.id}/path-alternatives', headers=headers, json={
            'line_path': line_path, 'mode': 'custom', 'selected_item_id': (selected or a).id,
            'members': [{'item_id': a.id, 'market_share': '60'},
                        {'item_id': candidate.id, 'market_share': '40'}], 'reason': reason})

    for invalid in [sibling, assembly, root]:
        response = configure(assembly, path, invalid)
        assert response.status_code == 409, response.text
        assert not list(db.scalars(select(models.PathAlternative)))
    assert configure(a, [999999], b).status_code == 409  # 无组成不能配置虚构路径
    assert configure(assembly, path, b, reason='').status_code == 422
    assert configure(assembly, path, b, selected=b).status_code == 200
    rows = services.production_bom(db, root.id, show_alternatives=True, expand_materials=True)
    current = {r['item']['id']: Decimal(r['quantity']) for r in rows if not r['is_backup_path']}
    assert current == {b.id: Decimal(9), sibling.id: Decimal(9)}
    assert any(r['item']['id'] == a.id and r['is_backup_path'] for r in rows)
    assert services.production_bom(db, root.id, expand_materials=False)[0]['item']['id'] == root.id
    nested = EffectiveBOM(db).rows(root.id)[1]['line_path']
    assert configure(root, nested, b, selected=a).status_code == 200
    assert EffectiveBOM(db).rows(assembly.id)[0]['item']['id'] == b.id
    assert EffectiveBOM(db).rows(root.id)[1]['item']['id'] == a.id
    assert db.get(models.BOMLine, path[0]).quantity == Decimal(3)
    history = client.get(f'/api/items/{assembly.id}/history', headers=headers)
    assert history.status_code == 200
    assert any(e['reason'] == '原材料选配' for e in history.json())
