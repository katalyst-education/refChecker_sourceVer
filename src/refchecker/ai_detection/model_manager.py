"""Download / status / delete for the local AI-text-detection model.

The local detector (desklib DeBERTa) is an **on-demand** download — it is
never bundled into the desktop sidecar (which deliberately excludes torch /
transformers to stay small) and never auto-downloads on first check.  Weights
live under a Tauri-resolved app-data directory passed via an env var, mirroring
the ``REFCHECKER_CACHE_DIR`` convention used elsewhere.

Download runs in a background thread and reports progress through a
module-level status dict, mirroring the existing local-database downloader UX
(poll ``status`` rather than streaming).
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

#: HuggingFace repo for the default local detector (DeBERTa-v3, MIT licence).
MODEL_REPO = "desklib/ai-text-detector-v1.01"
_MODEL_DIRNAME = "desklib-ai-text-detector-v1.01"

# Background download state (single global model, single download at a time).
_lock = threading.Lock()
_status: Dict[str, object] = {
    "state": "idle",        # idle | downloading | installed | error
    "message": "",
    "repo": MODEL_REPO,
}
_thread: Optional[threading.Thread] = None


def model_storage_dir() -> Path:
    """Directory that holds downloaded detection models."""
    env = os.environ.get("REFCHECKER_AI_DETECTION_MODEL_DIR")
    if env:
        return Path(env)
    cache = os.environ.get("REFCHECKER_CACHE_DIR")
    if cache:
        return Path(cache) / "ai-detection-models"
    return Path.home() / ".cache" / "refchecker" / "ai-detection-models"


def model_path() -> Path:
    """Filesystem path where the default local model is installed."""
    return model_storage_dir() / _MODEL_DIRNAME


_WEIGHT_FILES = ("model.onnx", "model.safetensors", "pytorch_model.bin")


def is_model_installed() -> bool:
    # Require an actual weight artifact, not just config.json — snapshot_download
    # writes the tiny config first, so checking only config.json would report
    # "installed" mid-download (premature poll-loop exit + a spurious
    # model_load_failed if a check starts before the weights land).
    p = model_path()
    if not (p.is_dir() and (p / "config.json").is_file()):
        return False
    return any((p / f).is_file() for f in _WEIGHT_FILES)


def _dir_size_bytes(path: Path) -> int:
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def model_status() -> Dict[str, object]:
    """Return current install/download status for the API + Settings UI."""
    installed = is_model_installed()
    with _lock:
        state = _status.get("state")
        message = _status.get("message", "")
    # If a previous process installed it, reflect that even when state==idle.
    if installed and state not in ("downloading",):
        state = "installed"
    size = _dir_size_bytes(model_path()) if installed else 0
    return {
        "state": state,
        "message": message,
        "installed": installed,
        "repo": MODEL_REPO,
        "path": str(model_path()),
        "size_bytes": size,
        "deps_available": deps_available(),
        **device_status(),
    }


def _onnx_deps_available() -> bool:
    try:
        import onnxruntime  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _torch_deps_available() -> bool:
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def deps_available() -> bool:
    """Whether the installed/downloadable weights have a usable runtime.

    ONNX Runtime can only load an actual ``model.onnx`` artifact. The managed
    desklib repository currently ships PyTorch safetensors, so before download
    (and for a safetensors-only install) require torch + transformers instead
    of reporting an ONNX-only environment as ready and failing during load.
    """
    p = model_path()
    if (p / "model.onnx").is_file() and _onnx_deps_available():
        return True
    if any((p / name).is_file() for name in ("model.safetensors", "pytorch_model.bin")):
        return _torch_deps_available()
    # The known managed download is safetensors-only.
    return _torch_deps_available()


def device_status() -> Dict[str, object]:
    """Return local-inference device capabilities for API/UI selection."""
    cuda_available = False
    cuda_device_name = None
    p = model_path()

    # Prefer the runtime matching installed weights. The managed checkpoint is
    # safetensors-only, so CUDA-enabled PyTorch is the normal GPU path.
    if any((p / name).is_file() for name in ("model.safetensors", "pytorch_model.bin")) \
            or not is_model_installed():
        try:
            import torch
            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                cuda_device_name = torch.cuda.get_device_name(0)
        except Exception:  # noqa: BLE001
            pass

    # A manually supplied ONNX model may use ONNX Runtime's CUDA provider.
    if not cuda_available and (p / "model.onnx").is_file():
        try:
            import onnxruntime as ort
            cuda_available = "CUDAExecutionProvider" in ort.get_available_providers()
            if cuda_available:
                cuda_device_name = "ONNX Runtime CUDA"
        except Exception:  # noqa: BLE001
            pass

    return {
        "cpu_available": deps_available(),
        "cuda_available": cuda_available,
        "cuda_device_name": cuda_device_name,
    }


def device_available(device: str) -> bool:
    normalized = (device or "cpu").strip().lower()
    if normalized == "gpu":
        normalized = "cuda"
    status = device_status()
    if normalized == "cpu":
        return bool(status["cpu_available"])
    if normalized == "cuda":
        return bool(status["cuda_available"])
    return False


def _download_worker() -> None:
    global _status
    try:
        from huggingface_hub import snapshot_download
    except Exception as exc:  # noqa: BLE001
        with _lock:
            _status = {"state": "error", "repo": MODEL_REPO,
                       "message": f"huggingface_hub not installed: {exc}"}
        return
    try:
        dest = model_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        with _lock:
            _status = {"state": "downloading", "repo": MODEL_REPO,
                       "message": f"Downloading {MODEL_REPO}…"}
        snapshot_download(
            repo_id=MODEL_REPO,
            local_dir=str(dest),
            local_dir_use_symlinks=False,
        )
        with _lock:
            _status = {"state": "installed", "repo": MODEL_REPO,
                       "message": "Model installed."}
        logger.info("AI-detection model installed at %s", dest)
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI-detection model download failed: %s", exc)
        with _lock:
            _status = {"state": "error", "repo": MODEL_REPO,
                       "message": f"Download failed: {exc}"}


def start_download() -> Dict[str, object]:
    """Kick off a background download (idempotent while one is running).

    The guard, state transition, and thread spawn happen in ONE locked
    critical section so two near-simultaneous callers can't both launch a
    snapshot_download into the same directory (TOCTOU).
    """
    global _thread, _status
    if is_model_installed():
        return model_status()
    with _lock:
        if _status.get("state") == "downloading" and _thread and _thread.is_alive():
            return dict(_status)
        # Mark downloading synchronously (the worker also sets it, but doing it
        # here closes the window before the thread first acquires the lock).
        _status = {"state": "downloading", "repo": MODEL_REPO,
                   "message": "Download started."}
        _thread = threading.Thread(target=_download_worker, daemon=True)
        _thread.start()
        return dict(_status)


def delete_model() -> Dict[str, object]:
    """Remove the installed model from disk.

    Refuses while a download is in flight and does the rmtree + state reset
    inside the SAME locked section as the download state machine, so a delete
    can't race a concurrent snapshot_download (which would recreate the dir and
    flip the state back to 'installed', silently undoing the delete).
    """
    global _status
    with _lock:
        if _status.get("state") == "downloading" and _thread and _thread.is_alive():
            return {"state": "downloading", "repo": MODEL_REPO,
                    "message": "Cannot remove the model while a download is in progress."}
        p = model_path()
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        _status = {"state": "idle", "repo": MODEL_REPO, "message": "Model removed."}
    return model_status()
