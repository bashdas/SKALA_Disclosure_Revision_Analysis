from pathlib import Path
from disclosure_ai.harness.ledger import Ledger


def test_report_keeps_utf8_markdown_file_and_sqlite_source(tmp_path):
    ledger=Ledger(str(tmp_path/'state.sqlite'))
    try:
        ledger.begin('task-id','fixed')
        content='# 정정공시 분석 보고서\n\n| 항목 | 값 |\n| --- | --- |\n| 기간 | 3개월 |'
        ledger.keep('task-id','report',{'content':content})
        path=tmp_path/'reports'/'task-id.md'
        assert path.read_text(encoding='utf-8')==content+'\n'
        assert path.stat().st_mode & 0o777 == 0o600
        assert '정정공시' in ledger.row('task-id')['report']
    finally:
        ledger.db.close()
