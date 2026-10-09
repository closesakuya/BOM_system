from backend.app.api import router


def test_finance_readonly_and_production_export(client, headers):
    created = client.post('/api/users', headers=headers, json={
        'username': 'finance_test', 'password': 'test-finance-only',
        'display_name': '财务测试', 'role': 'finance', 'active': True})
    assert created.status_code == 201, created.text
    login = client.post('/api/auth/login', json={'username': 'finance_test', 'password': 'test-finance-only'})
    assert login.status_code == 200
    finance = {'Authorization': 'Bearer ' + login.json()['access_token']}
    item = client.post('/api/items', headers=headers, json={
        'code': '10.8841.0', 'item_type': 'material', 'name': '财务权限测试',
        'source_type': 'purchased', 'similarity_confirmed': True}).json()
    item_id = item['id']
    for endpoint in ['/auth/me', '/items', '/audit', f'/items/{item_id}',
                     f'/items/{item_id}/technical-bom', f'/items/{item_id}/production-bom',
                     f'/items/{item_id}/history', f'/items/{item_id}/references']:
        assert client.get('/api' + endpoint, headers=finance).status_code == 200, endpoint
    result = client.get(f'/api/items/{item_id}/export/production', headers=finance)
    assert result.status_code == 200 and result.content.startswith(b'PK')
    batch = client.post('/api/bom/batch-export/production', headers=finance, json=[item_id])
    assert batch.status_code == 200 and batch.content.startswith(b'PK')
    technical = client.get(f'/api/items/{item_id}/export/technical', headers=finance)
    assert technical.status_code == 200 and technical.content.startswith(b'PK')
    for endpoint in ['/items-basic-export', '/audit/export',
                     '/compare/export?item_ids=' + str(item_id), '/imports/1/report', '/users']:
        assert client.get('/api' + endpoint, headers=finance).status_code == 403, endpoint
    # All business mutation routes must reject finance even if called directly.
    import re
    for route in router.routes:
        for method in route.methods & {'POST', 'PUT', 'PATCH', 'DELETE'}:
            if route.path in {'/api/auth/login', '/api/bom/batch-export/{bom_type}'}:
                continue
            url = re.sub(r'\{[^}]+\}', '1', route.path)
            response = client.request(method, url, headers=finance, json={})
            assert response.status_code == 403, (method, url, response.text)
    technical_batch = client.post('/api/bom/batch-export/technical', headers=finance, json=[item_id])
    assert technical_batch.status_code == 200 and technical_batch.content.startswith(b'PK')
    assert client.get(f'/api/items/{item_id}/export/technical', headers=headers).status_code == 200
