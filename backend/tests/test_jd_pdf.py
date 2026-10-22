"""JD PDF extraction: service validation plus the ops-only endpoint."""
from __future__ import annotations

from io import BytesIO
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.api.v1.packages import router as packages_router
from app.auth import HRUserContext, get_current_ops_user
from app.services.jd_pdf import (
    MAX_JD_CHARS,
    MAX_PDF_BYTES,
    JdPdfError,
    JdPdfTooLargeError,
    extract_jd_text,
)


def make_pdf(lines: list[str]) -> bytes:
    """Build a minimal one-page text-layer PDF (no new test dependency).

    Args:
        lines: Text lines rendered with a Type1 Helvetica Tj/T* stream.

    Returns:
        Raw PDF bytes parseable by pypdf.
    """
    ops = []
    for line in lines:
        esc = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        ops.append(f"({esc}) Tj T*")
    content = ("BT /F1 12 Tf 14 TL " + " ".join(ops) + " ET").encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF".encode()
    )
    return out.getvalue()


def blank_pdf(pages: int) -> bytes:
    """Build a valid PDF with no text layer (scanned-PDF stand-in)."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


JD_LINES = [
    "Senior Data Analyst",
    "Skills: Python, SQL and dashboards",
    "Own reporting for the growth team",
]


def test_extracts_text_from_text_layer_pdf():
    result = extract_jd_text(make_pdf(JD_LINES))
    assert result.page_count == 1
    assert result.truncated is False
    for line in JD_LINES:
        assert line in result.text


def test_rejects_empty_file():
    with pytest.raises(JdPdfError, match="empty"):
        extract_jd_text(b"")


def test_rejects_non_pdf_magic_bytes():
    with pytest.raises(JdPdfError, match="not a PDF"):
        extract_jd_text(b"PK\x03\x04 this is a zip, not a pdf")


def test_rejects_corrupt_pdf():
    with pytest.raises(JdPdfError, match="Could not read"):
        extract_jd_text(b"%PDF-1.4 garbage with no objects")


def test_rejects_scanned_pdf_without_text_layer():
    with pytest.raises(JdPdfError, match="scanned or"):
        extract_jd_text(blank_pdf(1))


def test_rejects_oversize_upload():
    with pytest.raises(JdPdfTooLargeError, match="10 MB"):
        extract_jd_text(b"%PDF-" + b"x" * MAX_PDF_BYTES)


def test_rejects_too_many_pages():
    with pytest.raises(JdPdfError, match="pages"):
        extract_jd_text(blank_pdf(51))


def test_truncates_overlong_jd_at_limit():
    long_line = " ".join(["responsibility"] * 200)
    result = extract_jd_text(make_pdf([long_line] * 300))
    assert result.truncated is True
    assert len(result.text) <= MAX_JD_CHARS


def _client(*, authenticated: bool) -> TestClient:
    application = FastAPI()
    application.include_router(packages_router, prefix="/api/v1/packages")
    if authenticated:

        async def _ops():
            return HRUserContext(user_id=uuid4(), corporate_id=uuid4(), role="admin")

        application.dependency_overrides[get_current_ops_user] = _ops
    return TestClient(application)


def _upload(client: TestClient, raw: bytes, filename: str = "jd.pdf"):
    return client.post(
        "/api/v1/packages/jd/extract-pdf",
        files={"file": (filename, BytesIO(raw), "application/pdf")},
    )


def test_endpoint_requires_ops_auth():
    response = _upload(_client(authenticated=False), make_pdf(JD_LINES))
    assert response.status_code in (401, 403, 422)
    assert response.status_code != 200


def test_endpoint_returns_extracted_text():
    response = _upload(_client(authenticated=True), make_pdf(JD_LINES))
    assert response.status_code == 200
    payload = response.json()
    assert "Senior Data Analyst" in payload["text"]
    assert payload["page_count"] == 1
    assert payload["char_count"] == len(payload["text"])
    assert payload["truncated"] is False


def test_endpoint_rejects_non_pdf_with_422():
    response = _upload(_client(authenticated=True), b"plain text, not a pdf")
    assert response.status_code == 422
    assert "not a PDF" in response.json()["detail"]


def test_endpoint_rejects_scanned_pdf_with_422():
    response = _upload(_client(authenticated=True), blank_pdf(1))
    assert response.status_code == 422
    assert "paste the job description" in response.json()["detail"]


def test_endpoint_rejects_oversize_with_413():
    response = _upload(
        _client(authenticated=True), b"%PDF-" + b"x" * MAX_PDF_BYTES
    )
    assert response.status_code == 413
