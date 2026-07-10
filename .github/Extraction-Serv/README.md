# Extraction-Serv

Minimal extraction microservice for RefChecker.

## Goal

This service encapsulates only reference extraction (URL, file, text) and vendors its required `service_core/` logic locally so it can run as a standalone repository.

It intentionally contains **no** verification, hallucination checks, or result presentation.

## Structure

- `app/main.py`: FastAPI endpoints
- `app/extractor.py`: copied and cleaned extraction logic from `backend/refchecker_wrapper.py`
- `app/models.py`: API models for extraction
- `tests/test_extract_api.py`: smoke/contract test
- `requirements.txt`: service-specific dependencies
- `Dockerfile`: container startup

## Run Locally

```powershell
cd C:\Users\dbigl\PycharmProjects\refchecker\Extraction-Serv
py -m uvicorn app.main:app --host 0.0.0.0 --port 8100
```

## Test

```powershell
cd C:\Users\dbigl\PycharmProjects\refchecker\Extraction-Serv
python -m pytest -q
```

## Endpoints

- `GET /health`
- `POST /extract` (multipart/form-data for `url|file|text`)
- `POST /extract/text` (JSON-only text input)

## Docker Build/Run

```powershell
cd C:\Users\dbigl\PycharmProjects\refchecker
docker build -f Extraction-Serv\Dockerfile -t extraction-serv .
docker run --rm -p 8100:8100 extraction-serv
```



