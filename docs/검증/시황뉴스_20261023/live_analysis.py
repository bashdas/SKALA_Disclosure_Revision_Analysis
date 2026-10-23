import json
import secrets
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx

D = Path(__file__).parent
credentials = Path("/tmp/disclosure-web-validation/news-test-account.json")
with httpx.Client(base_url="http://127.0.0.1:8080/api/v1", timeout=60) as client:
    def request(method, path, **kwargs):
        response = client.request(method, path, **kwargs)
        if response.is_error:
            raise RuntimeError(f"{method} {path}: HTTP {response.status_code}")
        return response.json()
    if not credentials.exists():
        account = {"email": "market-news-check-" + uuid4().hex[:12] + "@example.com",
                   "password": secrets.token_urlsafe(24)}
        request("POST", "/auth/signup", json={**account, "name": "시황 검증", "organization_name": "시황 기능 검증"})
        credentials.write_text(json.dumps(account))
        credentials.chmod(0o600)
    account = json.loads(credentials.read_text())
    token = request("POST", "/auth/login", json=account)["access_token"]
    client.headers["Authorization"] = "Bearer " + token
    today = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
    filings = request("GET", "/disclosures", params={"corp_code": "00164779", "start_date": "2026-10-01", "end_date": today})
    filing = next(row for row in filings["items"] if not row["is_correction"])
    request("POST", "/filings", json={"receipt_no": filing["receipt_no"]})
    content = """시황 통합 검증용 가정 메모입니다.
SK하이닉스의 전망을 검토할 때 AI 메모리 수요와 HBM 공급 확대가 주요 가정입니다.
메모의 이익 가정에는 반도체 업황이 큰 폭으로 둔화하지 않는다는 조건이 있습니다.
환율과 금리 변화가 수익성 및 자금 조달 환경에 미치는 영향은 시황 근거를 확인해 재검토해야 합니다.
새 기사만으로 실적이나 목표주가를 확정하지 않고 실제 공시와 기사에서 확인한 범위를 구분합니다.
"""
    memo = request("POST", "/memos", data={"title": "시황 통합 검증용 기존 메모", "company_id": "00164779"},
                   files={"file": ("market-validation-memo.txt", content.encode(), "text/plain")})
    (D / "live-analysis-input.json").write_text(json.dumps({"filing": filing, "memo": memo, "memo_content": content}, ensure_ascii=False, indent=2))
    task = request("POST", "/analyses", json={"memo_id": memo["id"], "memo_version": 1,
                   "disclosure_receipt_no": filing["receipt_no"]})
    (D / "live-task.json").write_text(json.dumps(task, indent=2))
    print("task", task["task_id"], "filing", filing["receipt_no"], flush=True)
    for _ in range(65):
        state = request("GET", "/analyses/" + task["task_id"])
        if state["status"] in {"COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED", "SAVE_FAILED", "CANCELLED"}:
            break
        time.sleep(2)
    report = request("GET", "/analyses/" + task["task_id"] + "/report")
    perspectives = request("GET", "/analyses/" + task["task_id"] + "/perspectives")
    (D / "live-analysis-result.json").write_text(json.dumps({"task": state, "perspectives": perspectives, "report": report}, ensure_ascii=False, indent=2))
    if report:
        (D / "live-report.md").write_text(report["content"])
    print("status", state["status"], "perspectives", [(p["perspective_type"], p["status"]) for p in perspectives], flush=True)
