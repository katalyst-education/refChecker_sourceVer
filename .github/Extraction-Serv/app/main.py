import os
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from .models import ExtractionResponse, TextExtractionRequest

app = FastAPI(title="Extraction Service", version="0.1.0")

UPLOAD_CHUNK_SIZE = 1024 * 1024
MAX_UPLOAD_FILE_BYTES = int(os.environ.get("MAX_UPLOAD_FILE_BYTES", str(25 * 1024 * 1024)))


def get_uploads_dir() -> Path:
    base = Path(os.environ.get("EXTRACTION_UPLOAD_DIR", str(Path(tempfile.gettempdir()) / "extraction_service_uploads")))
    base.mkdir(parents=True, exist_ok=True)
    return base


async def _save_upload_file(upload: UploadFile, dest_path: Path, max_bytes: int) -> int:
    total_bytes = 0
    try:
        with open(dest_path, "wb") as out_file:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_SIZE)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload exceeds maximum size of {max_bytes // (1024 * 1024)} MB",
                    )
                out_file.write(chunk)
    except Exception:
        if dest_path.exists():
            dest_path.unlink()
        raise
    return total_bytes


def _validate_remote_fetch_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are supported")
    if not parsed.netloc:
        raise ValueError("URL host is required")


def _get_service_class():
    # Lazy import keeps API startup light and lets tests stub the service.
    from .extractor import ExtractionService

    return ExtractionService


@app.get("/health")
async def health() -> dict:
    return {"status": "healthy"}


@app.post("/extract", response_model=ExtractionResponse)
async def extract(
    source_type: str = Form(...),
    source_value: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    source_text: Optional[str] = Form(None),
    llm_provider: str = Form("anthropic"),
    llm_model: Optional[str] = Form(None),
    use_llm: bool = Form(True),
    api_key: Optional[str] = Form(None),
    endpoint: Optional[str] = Form(None),
):
    paper_source = source_value

    if source_type == "file":
        if not file:
            raise HTTPException(status_code=400, detail="No file uploaded")
        uploads_dir = get_uploads_dir()
        safe_filename = (file.filename or "upload.bin").replace("/", "_").replace("\\", "_")
        file_path = uploads_dir / safe_filename
        await _save_upload_file(file, file_path, MAX_UPLOAD_FILE_BYTES)
        paper_source = str(file_path)
    elif source_type == "text":
        if not source_text:
            raise HTTPException(status_code=400, detail="No text provided")
        paper_source = source_text.replace("\r\n", "\n").replace("\r", "\n")
    elif source_type == "url":
        if not source_value:
            raise HTTPException(status_code=400, detail="No URL provided")
        parsed = urlparse(source_value)
        if parsed.scheme or parsed.netloc:
            try:
                _validate_remote_fetch_url(source_value)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=400, detail="Unsupported source_type")

    service = _get_service_class()(
        llm_provider=llm_provider,
        llm_model=llm_model,
        api_key=api_key,
        endpoint=endpoint,
        use_llm=use_llm,
    )
    result = await service.extract(paper_source=paper_source, source_type=source_type)
    return result


@app.post("/extract/text", response_model=ExtractionResponse)
async def extract_text(request: TextExtractionRequest):
    service = _get_service_class()(
        llm_provider=request.llm_provider,
        llm_model=request.llm_model,
        api_key=request.api_key,
        endpoint=request.endpoint,
        use_llm=request.use_llm,
    )
    return await service.extract(paper_source=request.source_text, source_type="text")


