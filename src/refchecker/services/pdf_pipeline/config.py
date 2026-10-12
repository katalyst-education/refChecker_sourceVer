import math
import os

GROBID_BASE_URL = (
    os.environ.get("GROBID_URL", "http://localhost:8070").strip().rstrip("/")
    or "http://localhost:8070"
)
if GROBID_BASE_URL.endswith("/api/processFulltextDocument"):
    GROBID_URL = GROBID_BASE_URL
elif GROBID_BASE_URL.endswith("/api"):
    GROBID_URL = f"{GROBID_BASE_URL}/processFulltextDocument"
else:
    GROBID_URL = f"{GROBID_BASE_URL}/api/processFulltextDocument"

try:
    GROBID_METADATA_TIMEOUT = float(
        os.environ.get("GROBID_METADATA_TIMEOUT", "10")
    )
except ValueError as exc:
    raise ValueError(
        "GROBID_METADATA_TIMEOUT must be a positive number of seconds"
    ) from exc
if not math.isfinite(GROBID_METADATA_TIMEOUT) or GROBID_METADATA_TIMEOUT <= 0:
    raise ValueError(
        "GROBID_METADATA_TIMEOUT must be a positive number of seconds"
    )

MAX_CLASSIFIER_PAGES = 10