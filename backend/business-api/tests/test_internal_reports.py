from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from app.main import app
from app.api.dependencies import get_current_user, get_disclosure_source
from app.api.internal_report import get_report_service
from app.models.enums import UserRole
from app.schemas.auth import CurrentUser
from app.services.internal_report import InternalReportService, extract_pdf
from test_domain import graph, migrated_engine
from sqlalchemy.orm import Session


@pytest.fixture
def db(migrated_engine):
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


def pdf(text="Company forecast"):
    writer = PdfWriter()
    page = writer.add_blank_page(300, 300)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 20 200 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = stream
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_rejects_invalid_and_empty_documents():
    from fastapi import HTTPException
    for raw in (b"not a pdf", b"%PDF-broken"):
        with pytest.raises(HTTPException):
            extract_pdf(BytesIO(raw), "report.pdf")
    result = extract_pdf(BytesIO(pdf()), "report.pdf")
    assert result["pages"][0]["page"] == 1
    assert "Company forecast" in result["content"]


@pytest.mark.postgres
def test_report_crud_shared_readers_and_fixed_versions(db, graph):
    service = InternalReportService(db)
    principal = CurrentUser(id=graph.user.id, email=graph.user.email, role=UserRole.ANALYST)
    graph.task.corp_code = graph.filing.corp_code = "00126478"
    db.flush()
    class Source:
        def call(self, *args):
            return {"items": [{"corp_code": "00126478", "company_name": "Company"}]}
    old = app.dependency_overrides.copy()
    app.dependency_overrides[get_current_user] = lambda: principal
    app.dependency_overrides[get_report_service] = lambda: service
    app.dependency_overrides[get_disclosure_source] = Source
    try:
        with TestClient(app) as client:
            data = {"title": "Internal forecast", "corp_code": "00126478", "published_at": "2026-01-01"}
            response = client.post("/api/v1/internal-reports", data=data,
                files={"file": ("report.pdf", pdf(), "application/pdf")})
            assert response.status_code == 201, response.text
            report = response.json()
            path = "/api/v1/internal-reports/" + report["id"]
            assert client.get(path).json()["content"].startswith("[1쪽]")
            first = service.for_analysis(graph.task.id)["reports"]
            assert first[0]["version"] == 1
            changed = client.post(path + "/versions", data={"base_version": 1},
                files={"file": ("new.pdf", pdf("New forecast"), "application/pdf")})
            assert changed.status_code == 200 and changed.json()["current_version"] == 2
            assert service.for_analysis(graph.task.id)["reports"][0]["version"] == 1
            assert client.patch(path, json={**data, "base_version": 1}).status_code == 409
            principal = principal.model_copy(update={"role": UserRole.RA})
            assert client.get(path + "/file?version=1").content == pdf()
            assert client.delete(path).status_code == 403
            assert client.patch(path, json={**data, "base_version": 2}).status_code == 403
            assert client.post(path + "/versions", data={"base_version": 2},
                files={"file": ("new.pdf", pdf(), "application/pdf")}).status_code == 403
            assert client.post("/api/v1/internal-reports", data=data,
                files={"file": ("new.pdf", pdf(), "application/pdf")}).status_code == 403
            # Another employee reads the same company database.
            principal = principal.model_copy(update={"id": uuid4(), "email": "reader@example.test"})
            assert client.get(path).status_code == 200
            assert client.get("/api/v1/internal-reports").json()[0]["id"] == report["id"]
            principal = principal.model_copy(update={"role": UserRole.ANALYST})
            assert client.delete(path).status_code == 204
            assert client.get(path).status_code == 404
            assert not service.for_analysis(graph.task.id)["reports"]
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old)
