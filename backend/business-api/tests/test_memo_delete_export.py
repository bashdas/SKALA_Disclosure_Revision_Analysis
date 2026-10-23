from datetime import datetime, timezone
from uuid import UUID
import pytest
from app.core.security import create_access_token
from app.models import AnalysisReport, Memo, MemoVersion
from app.services.report_export import report_html
from test_analysis_api import analysis_context, analysis_client, request
from test_auth_security import auth_settings
from test_domain import migrated_engine


def test_markdown_export_escapes_html_and_retains_tables():
    html=report_html('# 한글 보고서\n\n| 항목 | 값 |\n| --- | --- |\n| 기간 | 3개월 |\n\n<script>alert(1)</script>\n\n![이미지](file:///etc/passwd)')
    assert '<h1>한글 보고서</h1>' in html and '<table>' in html
    assert '<script>' not in html and '<img' not in html


@pytest.mark.postgres
def test_deleted_memo_cannot_start_analysis_and_old_report_remains(analysis_client, analysis_context):
    ctx=analysis_context
    headers={'Authorization':'Bearer '+create_access_token(ctx.users[0],settings=ctx.settings)}
    other={'Authorization':'Bearer '+create_access_token(ctx.users[1],settings=ctx.settings)}
    accepted=request(analysis_client,ctx)
    assert accepted.status_code==202
    task=accepted.json()['task_id']
    content='# 검증 보고서\n\n| 항목 | 값 |\n| --- | --- |\n| 기간 | 3개월 |\n'
    with ctx.factory() as db:
        db.add(AnalysisReport(analysis_task_id=UUID(task),content=content,report_json={},generated_at=datetime.now(timezone.utc),saved_at=datetime.now(timezone.utc)))
        db.commit()
    path=f'/api/v1/memos/{ctx.memos[0].id}'
    assert analysis_client.delete(path).status_code==401
    assert analysis_client.delete(path,headers=other).status_code==204
    assert str(ctx.memos[0].id) not in [row['id'] for row in analysis_client.get('/api/v1/memos',headers=headers).json()]
    assert request(analysis_client,ctx).status_code==404
    assert analysis_client.get(path+'/versions/3',headers=headers).json()['content']=='company memo body'
    report_path=f'/api/v1/analyses/{task}/report'
    assert analysis_client.get(report_path,headers=headers).json()['content']==content
    md=analysis_client.get(report_path+'.md',headers=headers)
    assert md.status_code==200 and md.text==content
    assert 'attachment;' in md.headers['content-disposition']
    assert analysis_client.get(report_path+'.md',headers=other).text==content
    for suffix in ('.md','.pdf'):
        response=analysis_client.get(report_path+suffix,headers=other)
        assert response.status_code==200
        if suffix=='.pdf':
            assert response.content.startswith(b'%PDF-')
        assert analysis_client.get(report_path+suffix).status_code==401
    assert analysis_client.delete(path,headers=headers).status_code==204
    with ctx.factory() as db:
        assert db.get(Memo,ctx.memos[0].id).is_deleted
