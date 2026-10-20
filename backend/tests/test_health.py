from fastapi.testclient import TestClient

from app.main import app


def test_health_only_claims_api_liveness():
    response = TestClient(app).get('/api/health')
    assert response.status_code == 200
    assert response.json() == {
        'status': 'ok', 'service': 'content-intelligence-api', 'version': '0.1.0'
    }
    assert 'database' not in response.json()


def test_health_contract_is_in_openapi():
    schema = TestClient(app).get('/openapi.json').json()
    assert '/api/health' in schema['paths']
