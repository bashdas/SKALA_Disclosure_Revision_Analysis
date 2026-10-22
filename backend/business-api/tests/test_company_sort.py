from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user, get_disclosure_source
from app.api.disclosure import router
from app.models.enums import UserRole
from app.schemas.auth import CurrentUser


def test_company_sort_validation_and_pagination_are_forwarded_to_mcp():
    calls = []

    class Source:
        def call(self, name, args):
            calls.append((name, args))
            return {'items': [], 'total_count': 0, 'has_more': False}

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=uuid4(), organization_id=uuid4(), email='test@example.com', role=UserRole.ANALYST,
    )
    app.dependency_overrides[get_disclosure_source] = Source
    with TestClient(app) as client:
        snapshot = 'a' * 32
        response = client.get('/api/v1/disclosures/companies', params={
            'sort': 'market_cap_desc', 'offset': 20, 'snapshot': snapshot, 'query': '삼성',
        })
        assert response.status_code == 200
        assert calls[-1] == ('opendart_search_companies', {
            'query': '삼성', 'offset': 20, 'limit': 20, 'seed': '',
            'sort': 'market_cap_desc', 'snapshot': snapshot,
        })
        assert client.get('/api/v1/disclosures/companies?sort=name').status_code == 200
        assert calls[-1][1]['sort'] == 'name'
        assert client.get('/api/v1/disclosures/companies').status_code == 200
        assert calls[-1][1] == {'query': '', 'offset': 0, 'limit': 20, 'seed': ''}
        for params in ({'sort': 'invalid'}, {'snapshot': '../bad'}, {'offset': -1}):
            assert client.get('/api/v1/disclosures/companies', params=params).status_code == 422
