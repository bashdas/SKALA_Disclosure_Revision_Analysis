from uuid import UUID
import pytest
from app.api.dependencies import get_disclosure_source
from app.core.security import create_access_token
from app.main import app
from app.models import Filing
from app.services.internal_analysis import InternalAnalysisService
from test_analysis_api import analysis_context, analysis_client, request
from test_auth_security import auth_settings
from test_domain import migrated_engine

ROOT='20261020000001'
CORRECTION='20261021000001'

class Source:
    def call(self, tool, arguments):
        if tool == 'opendart_search_companies':
            return {'items':[{'corp_code':'00126380','company_name':'삼성전자','stock_code':'005930'}]}
        if tool == 'opendart_get_disclosure_family':
            return {'items':[{'receipt_no':ROOT,'is_correction':False},{'receipt_no':CORRECTION,'is_correction':True}]}
        receipt=arguments['receipt_no']
        return {'receipt_no':receipt,'corp_code':'00126380','company_name':'삼성전자','report_name':'[기재정정]공급계약' if receipt==CORRECTION else '공급계약','filed_at':'2026-10-21','metadata_status':'FOUND','document':{'text':'확인한 공시 원문입니다.'}}

@pytest.mark.postgres
def test_favorites_corrections_and_analysis_gate(analysis_client,analysis_context):
    ctx=analysis_context
    headers={'Authorization':'Bearer '+create_access_token(ctx.users[0],settings=ctx.settings)}
    other={'Authorization':'Bearer '+create_access_token(ctx.users[1],settings=ctx.settings)}
    previous=app.dependency_overrides.get(get_disclosure_source)
    app.dependency_overrides[get_disclosure_source]=lambda:Source()
    try:
        assert analysis_client.get('/api/v1/disclosures/companies', headers=headers).status_code == 200
        for _ in range(2):
            assert analysis_client.post('/api/v1/favorites',headers=headers,json={'corp_code':'00126380'}).status_code==200
        assert len(analysis_client.get('/api/v1/favorites',headers=headers).json())==1
        assert analysis_client.get('/api/v1/favorites',headers=other).json()==[]
        root=analysis_client.post('/api/v1/filings',headers=headers,json={'receipt_no':ROOT})
        assert root.status_code==200 and not root.json()['is_correction']
        accepted = request(analysis_client,ctx,receipt=ROOT)
        assert accepted.status_code == 202
        with ctx.factory() as db:
            metadata = InternalAnalysisService(db, ctx.settings).get_context(UUID(accepted.json()['task_id']))
            assert metadata.filing_type == '신규공시' and metadata.is_correction is False
            assert metadata.memo.version == ctx.memos[0].current_version
        root_id=root.json()['id']
        path=f'/api/v1/filings/{root_id}/corrections/check'
        assert analysis_client.post(path,headers=other).status_code==404
        children=analysis_client.post(path,headers=headers).json()
        assert len(children)==1 and children[0]['is_correction']
        assert children[0]['origin_receipt_no']==ROOT
        assert len(analysis_client.post(path,headers=headers).json())==1
        assert request(analysis_client,ctx,receipt=CORRECTION).status_code==202
        assert analysis_client.delete(f'/api/v1/filings/{root_id}',headers=headers).status_code==204
        rows=analysis_client.get('/api/v1/filings',headers=headers).json()
        assert not any(row['receipt_no'] in (ROOT,CORRECTION) for row in rows)
        with ctx.factory() as db:
            assert db.get(Filing,UUID(root_id)) is not None
        assert request(analysis_client,ctx,receipt=CORRECTION).json()['error']['code']=='REGISTERED_FILING_REQUIRED'
        assert analysis_client.delete('/api/v1/favorites/00126380',headers=headers).status_code==204
    finally:
        if previous is None:app.dependency_overrides.pop(get_disclosure_source,None)
        else:app.dependency_overrides[get_disclosure_source]=previous
