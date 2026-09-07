import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from fastapi.testclient import TestClient

import backend.pdf_convert as pdf_convert
from backend import main as backend_main
from backend.auth import UserInfo, require_user


def _write_minimal_docx(path: Path, text: str) -> None:
    body = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        f"<w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("word/document.xml", body)


def _client_for(check, monkeypatch, cache_dir: Path):
    app = backend_main.app
    app.dependency_overrides[require_user] = lambda: UserInfo(id=1, provider="test")

    async def _fake_owned(check_id, user):
        return dict(check, id=check_id)

    async def _fake_cache_dir():
        cache_dir.mkdir(parents=True, exist_ok=True)
        return str(cache_dir)

    monkeypatch.setattr(backend_main, "_get_owned_check_or_404", _fake_owned)
    monkeypatch.setattr(backend_main, "_get_configured_cache_dir", _fake_cache_dir)
    return TestClient(app)


def _write_fake_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Minimal valid PNG (1x1 transparent pixel)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
        b"\x00\x00\x00\x0cIDATx\x9cc`\x00\x00\x00\x02\x00\x01\xe2!\xbc3"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )


def test_paper_text_recovers_from_missing_docx_txt(monkeypatch, tmp_path):
    docx_path = tmp_path / "paper.docx"
    _write_minimal_docx(docx_path, "This paper cites Smith 2020 in the references section.")
    converted_txt_path = docx_path.with_suffix(".docx.txt")
    assert not converted_txt_path.exists()

    client = _client_for(
        {"source_type": "file", "paper_source": str(converted_txt_path)},
        monkeypatch,
        tmp_path / "cache",
    )
    try:
        resp = client.get("/api/paper-text/101")
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["available"] is True
        assert "Smith 2020" in payload["text"]
        assert converted_txt_path.exists()
    finally:
        backend_main.app.dependency_overrides.clear()


def test_preview_recovers_from_missing_docx_txt(monkeypatch, tmp_path):
    docx_path = tmp_path / "paper.docx"
    _write_minimal_docx(docx_path, "Preview must recover from missing converted DOCX text.")
    converted_txt_path = docx_path.with_suffix(".docx.txt")
    assert not converted_txt_path.exists()

    async def _fake_text_preview(check_id, text_preview="", text_file_path="", source_identifier=None, cache_dir=None):
        out = tmp_path / "cache" / f"{check_id}_preview.png"
        _write_fake_png(out)
        return str(out)

    monkeypatch.setattr(backend_main, "get_text_preview_async", _fake_text_preview)

    client = _client_for(
        {"source_type": "file", "paper_source": str(converted_txt_path)},
        monkeypatch,
        tmp_path / "cache",
    )
    try:
        resp = client.get("/api/preview/303")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("image/png")
        assert converted_txt_path.exists()
    finally:
        backend_main.app.dependency_overrides.clear()


def test_thumbnail_recovers_from_missing_docx_txt(monkeypatch, tmp_path):
    docx_path = tmp_path / "paper.docx"
    _write_minimal_docx(docx_path, "Thumbnail must recover from missing converted DOCX text.")
    converted_txt_path = docx_path.with_suffix(".docx.txt")
    assert not converted_txt_path.exists()

    async def _fake_text_thumbnail(check_id, text_preview="", text_file_path="", source_identifier=None, cache_dir=None):
        out = tmp_path / "cache" / f"{check_id}_thumb.png"
        _write_fake_png(out)
        return str(out)

    monkeypatch.setattr(backend_main, "get_text_thumbnail_async", _fake_text_thumbnail)

    client = _client_for(
        {"source_type": "file", "paper_source": str(converted_txt_path)},
        monkeypatch,
        tmp_path / "cache",
    )
    try:
        resp = client.get("/api/thumbnail/404")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("image/png")
        assert converted_txt_path.exists()
    finally:
        backend_main.app.dependency_overrides.clear()


def test_paper_pdf_recovers_from_missing_docx_txt(monkeypatch, tmp_path):
    docx_path = tmp_path / "paper.docx"
    _write_minimal_docx(docx_path, "Recovered DOCX text should be rendered into a PDF fallback.")
    converted_txt_path = docx_path.with_suffix(".docx.txt")
    assert not converted_txt_path.exists()

    def _fake_text_to_pdf(text: str, output_path: str, title: str = None):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"%PDF-1.4\n%fake\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF")

    monkeypatch.setattr(pdf_convert, "text_to_pdf", _fake_text_to_pdf)

    client = _client_for(
        {"source_type": "file", "paper_source": str(converted_txt_path)},
        monkeypatch,
        tmp_path / "cache",
    )
    try:
        resp = client.get("/api/paper-pdf/202")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("application/pdf")
        assert resp.content.startswith(b"%PDF-1.4")
        assert converted_txt_path.exists()
    finally:
        backend_main.app.dependency_overrides.clear()
