from hashlib import sha256
from io import BytesIO
from uuid import UUID

from fastapi import HTTPException
from pypdf import PdfReader
from sqlalchemy import select

from app.models import InternalReport, InternalReportVersion, AnalysisReportReference, AnalysisTask, Filing

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_TEXT_CHARS = 1_000_000


def extract_pdf(stream, filename):
    name = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    if not name.lower().endswith(".pdf") or len(name) > 255 or any(ord(c) < 32 for c in name):
        raise HTTPException(422, "PDF 파일을 등록해 주세요.")
    raw = stream.read(MAX_PDF_BYTES + 1)
    if len(raw) > MAX_PDF_BYTES:
        raise HTTPException(413, "PDF는 20 MiB 이하로 등록해 주세요.")
    try:
        if not raw.startswith(b"%PDF-"):
            raise ValueError()
        reader = PdfReader(BytesIO(raw))
        if reader.is_encrypted or len(reader.pages) > 300:
            raise ValueError()
        pages, total = [], 0
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").replace("\x00", "")
            total += len(text)
            if total > MAX_TEXT_CHARS:
                raise ValueError()
            pages.append({"page": number, "text": text})
        if not any(p["text"].strip() for p in pages):
            raise ValueError()
    except Exception:
        raise HTTPException(422, "텍스트를 추출할 수 있는 암호화되지 않은 PDF가 필요합니다 (최대 300쪽·100만 자).") from None
    content = "\n\n".join(f"[{p['page']}쪽]\n{p['text']}" for p in pages)
    return dict(pdf_data=raw, pages=pages, content=content, original_filename=name, content_hash=sha256(raw).hexdigest())


class InternalReportService:
    def __init__(self, session):
        self.session = session

    def get(self, report_id, organization_id, lock=False):
        stmt = select(InternalReport).where(InternalReport.id == report_id,
            InternalReport.organization_id == organization_id, InternalReport.is_deleted.is_(False))
        row = self.session.scalar(stmt.with_for_update() if lock else stmt)
        if row is None:
            raise HTTPException(404, "내부 리포트를 찾을 수 없습니다.")
        return row

    def version(self, report, version=None):
        row = self.session.scalar(select(InternalReportVersion).where(
            InternalReportVersion.report_id == report.id,
            InternalReportVersion.version == (version or report.current_version)))
        if row is None:
            raise HTTPException(404, "리포트 버전을 찾을 수 없습니다.")
        return row

    def list(self, organization_id, limit, offset, corp_code=None):
        stmt = select(InternalReport).where(InternalReport.organization_id == organization_id,
            InternalReport.is_deleted.is_(False))
        if corp_code:
            stmt = stmt.where(InternalReport.corp_code == corp_code)
        return self.session.scalars(stmt.order_by(InternalReport.created_at.desc(), InternalReport.id).limit(limit).offset(offset)).all()

    def save(self, user, metadata, company_name, extracted=None, report_id=None, base_version=None):
        try:
            if report_id:
                report = self.get(report_id, user.organization_id, lock=True)
                if report.current_version != base_version:
                    raise HTTPException(409, "리포트가 변경되었습니다. 다시 조회해 주세요.")
                previous = self.version(report)
                report.current_version += 1
                if extracted is None:
                    extracted = {key: getattr(previous, key) for key in (
                        "pdf_data", "pages", "content", "original_filename", "content_hash")}
            else:
                report = InternalReport(organization_id=user.organization_id, current_version=1)
                self.session.add(report)
            for key, value in metadata.items():
                setattr(report, key, value)
            report.company_name = company_name
            self.session.flush()
            self.session.add(InternalReportVersion(report_id=report.id, version=report.current_version,
                created_by=user.id, company_name=company_name, **metadata, **extracted))
            self.session.commit()
            return report
        except Exception:
            self.session.rollback()
            raise

    def delete(self, report_id, organization_id):
        try:
            report = self.get(report_id, organization_id, lock=True)
            report.is_deleted = True
            self.session.commit()
        except Exception:
            self.session.rollback()
            raise

    def for_analysis(self, task_id):
        # A task-owned snapshot is fixed once, including empty manifests. No client org/cutoff input.
        try:
            task = self.session.scalar(select(AnalysisTask).where(AnalysisTask.id == task_id).with_for_update())
            if task is None:
                raise HTTPException(404, "분석을 찾을 수 없습니다.")
            manifest = self.session.get(AnalysisReportReference, task_id)
            if manifest is None:
                filing = self.session.scalar(select(Filing).where(Filing.organization_id == task.organization_id,
                    Filing.receipt_no == task.disclosure_receipt_no))
                if filing is None or filing.filed_at is None:
                    raise HTTPException(409, "공시 기준일을 확인하지 못했습니다.")
                cutoff = filing.filed_at.date()
                versions = self.session.scalars(select(InternalReportVersion).join(InternalReport,
                    InternalReport.id == InternalReportVersion.report_id).where(
                    InternalReport.organization_id == task.organization_id,
                    InternalReport.is_deleted.is_(False), InternalReport.corp_code == task.corp_code,
                    InternalReportVersion.version == InternalReport.current_version,
                    InternalReportVersion.corp_code == task.corp_code,
                    InternalReportVersion.published_at <= cutoff).order_by(InternalReport.id).limit(101)).all()
                if len(versions) > 100:
                    raise HTTPException(409, "분석 대상 내부 리포트가 100개를 초과했습니다.")
                manifest = AnalysisReportReference(task_id=task_id, versions=[str(v.id) for v in versions])
                self.session.add(manifest)
                self.session.flush()
            versions = self.session.scalars(select(InternalReportVersion).join(InternalReport,
                InternalReport.id == InternalReportVersion.report_id).where(
                InternalReportVersion.id.in_([UUID(v) for v in manifest.versions]),
                InternalReport.organization_id == task.organization_id,
                InternalReport.is_deleted.is_(False)).order_by(InternalReport.id)).all()
            reports = [{"report_id": str(v.report_id), "version": v.version, "title": v.title,
                "corp_code": v.corp_code, "company_name": v.company_name,
                "published_at": v.published_at.isoformat(), "source_file": v.original_filename,
                "text": v.content, "pages": v.pages, "content_hash": v.content_hash} for v in versions]
            self.session.commit()
            return {"task_id": str(task_id), "organization_id": str(task.organization_id), "reports": reports}
        except Exception:
            self.session.rollback()
            raise
