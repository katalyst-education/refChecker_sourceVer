"""Local calibrated detector backend (default engine).

Runs the desklib ``ai-text-detector-v1.01`` model (DeBERTa-v3, MIT) entirely
offline.  Preferred runtime is ``onnxruntime`` (PyInstaller-friendly, small);
falls back to ``transformers`` + ``torch`` when only those are installed.  All
ML imports are lazy and wrapped — a missing dependency or un-downloaded model
yields an "unavailable" result, never a crash.

Scoring is windowed (>= ~350-word windows, 50 % overlap).  The document score
is the **mean** of window probabilities (a conservative aggregate — taking the
max over many windows would inflate false positives).  A span is surfaced only
when it AND an overlapping neighbour both clear the high threshold, so single
noisy windows never produce an accusation.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, List, Optional

from .base import (
    AIDetectionResult,
    DetectionBackend,
    SuspectSpan,
    BAND_MEDIUM,
    HIGH_THRESHOLD,
    OPERATING_POINT,
    DISCLAIMER,
    BAND_HIGH,
    band_from_probability,
    band_rank,
    iter_windows,
    make_inconclusive,
    make_unavailable,
    prepared_text,
    record_detection_usage,
    should_abstain,
    truncate_quote,
)
from . import model_manager

logger = logging.getLogger(__name__)

_MAX_TOKENS = 768  # per-window truncation for the encoder

# Module-level model cache so we load weights once per device per process.
# Keeping CPU and CUDA entries separate prevents the first request's device
# from silently determining all later checks.
_engines = {}
_engine_lock = threading.Lock()

_VALID_DEVICES = ("cpu", "cuda")


def _normalize_device(device: Optional[str]) -> str:
    value = (device or "cpu").strip().lower()
    if value == "gpu":
        value = "cuda"
    return value


def _ai_positive_index(id2label: Optional[Dict]) -> Optional[int]:
    """Pick the logit index whose label denotes AI/generated text.

    Returns the index, or None if it cannot be determined unambiguously (e.g.
    ``LABEL_0``/``LABEL_1``). Callers MUST abstain rather than guess when this
    returns None — guessing can invert the score and flag human text as AI,
    the worst possible honesty failure for this feature.
    """
    if not id2label:
        return None
    keys = ("fake", "generated", "machine", "llm", "gpt", "synthetic", "chatgpt")
    matches = []
    for idx, label in id2label.items():
        lab = str(label).strip().lower()
        if lab == "ai" or lab.startswith(("ai-", "ai_", "ai ")) or any(k in lab for k in keys):
            matches.append(int(idx))
    return matches[0] if len(matches) == 1 else None


class LocalDetectorBackend(DetectionBackend):
    name = "local"

    def __init__(self, check_id=None, device: str = "cpu"):
        self.model_version = f"local:{model_manager.MODEL_REPO}"
        self.check_id = check_id
        self.device = _normalize_device(device)

    @property
    def available(self) -> bool:
        return (
            self.device in _VALID_DEVICES
            and model_manager.is_model_installed()
            and model_manager.deps_available()
            and model_manager.device_available(self.device)
        )

    def detect(self, text: str, *, title: Optional[str] = None) -> AIDetectionResult:
        body, wc = prepared_text(text)
        if not model_manager.is_model_installed():
            result = make_unavailable("model_not_installed", self.name, wc)
            result.device_used = self.device
            return result
        if not model_manager.deps_available():
            result = make_unavailable("deps_not_installed", self.name, wc)
            result.device_used = self.device
            return result
        if self.device not in _VALID_DEVICES:
            result = make_unavailable("invalid_device", self.name, wc)
            result.device_used = self.device
            return result
        if not model_manager.device_available(self.device):
            result = make_unavailable("device_unavailable", self.name, wc)
            result.device_used = self.device
            return result
        reason = should_abstain(body)
        if reason:
            result = make_inconclusive(reason, self.name, wc)
            result.device_used = self.device
            return result

        try:
            engine = _get_engine(self.device)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Local detector load failed: %s", exc)
            result = make_unavailable("model_load_failed", self.name, wc)
            result.device_used = self.device
            return result

        # Only score windows that independently clear the SAME reliability
        # floors the document had to clear (>= MIN_WORDS prose, non-prose
        # fraction <= the abstain threshold). This prevents an equation- /
        # citation-dense window inside an otherwise-prose manuscript from
        # being scored and surfaced as a flagged passage — detectors are
        # documented as unreliable on exactly that terrain.
        # Keep each retained window's ORIGINAL position so span corroboration
        # can require *physical* adjacency (overlap), not just list adjacency
        # after non-prose windows were dropped.
        kept = [(i, w) for i, w in enumerate(iter_windows(body)) if should_abstain(w) is None]
        if not kept:
            return make_inconclusive("insufficient_signal", self.name, wc)
        orig_idx = [i for i, _ in kept]
        windows = [w for _, w in kept]
        try:
            probs = [engine.score(w) for w in windows]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Local detector inference failed: %s", exc)
            result = make_unavailable("inference_failed", self.name, wc)
            result.device_used = self.device
            return result

        doc_score = round(sum(probs) / len(probs), 3)
        raw_band = band_from_probability(doc_score)
        band = raw_band
        # A standalone 'high' document band requires >= 2 assessable windows
        # (the mean already needed broad agreement to clear HIGH_THRESHOLD). A
        # lone high-scoring window stays advisory — cap it at medium so a single
        # noisy window never drives a 'high' verdict. (Span surfacing applies a
        # stricter physical-adjacency rule on top of this; see _agreeing_spans.)
        if band == BAND_HIGH and len(windows) < 2:
            band = BAND_MEDIUM
        # When that cap lowered the band, suppress the surfaced score so the UI
        # never shows "Medium · score 90" — reading a number higher than the
        # (capped) band is confusing dissonance. Mirrors the LLM backend.
        surfaced_score = None if band_rank(band) < band_rank(raw_band) else doc_score

        # Local inference is free: record the processed word count for the
        # usage meter (tokens proxy) with $0 cost.
        record_detection_usage(self.check_id, self.model_version, input_tokens=wc, cost_usd=0.0)

        spans = _agreeing_spans(windows, probs, orig_idx) if band_rank(band) >= band_rank(BAND_MEDIUM) else []

        return AIDetectionResult(
            band=band,
            overall_score=surfaced_score,
            confidence="medium",
            summary=_summary(band, surfaced_score, len(windows)),
            spans=spans,
            backend_used=self.name,
            model_version=self.model_version,
            device_used=self.device,
            operating_point=OPERATING_POINT,
            word_count=wc,
            disclaimer=DISCLAIMER,
        )


def _agreeing_spans(windows: List[str], probs: List[float],
                    orig_idx: List[int]) -> List[SuspectSpan]:
    """Surface windows above the high threshold that have a high neighbour.

    Corroboration requires a neighbour that is BOTH list-adjacent AND
    physically adjacent in the document (original window index differs by 1, so
    the two windows actually overlap). A dropped non-prose window between two
    retained ones breaks the chain — preventing a spurious "agreement" drawn
    from two passages that don't actually border each other.
    """
    spans: List[SuspectSpan] = []
    n = len(windows)
    for i, p in enumerate(probs):
        if p < HIGH_THRESHOLD:
            continue
        neighbour_high = (
            (i > 0 and probs[i - 1] >= HIGH_THRESHOLD and orig_idx[i] - orig_idx[i - 1] == 1)
            or (i < n - 1 and probs[i + 1] >= HIGH_THRESHOLD and orig_idx[i + 1] - orig_idx[i] == 1)
        )
        if not neighbour_high:
            continue
        spans.append(SuspectSpan(
            quote=truncate_quote(windows[i]),
            reason="This passage scored above the high-likelihood threshold.",
            confidence="medium",
        ))
        if len(spans) >= 6:
            break
    return spans


def _summary(band: str, score, n_windows: int) -> str:
    base = {
        "low": "No strong indicators of AI-generated prose.",
        "medium": "Some indicators present; not conclusive.",
        "high": "Multiple indicators present — this is NOT proof of AI authorship.",
    }.get(band, "")
    if score is None:
        return f"{base} (assessed {n_windows} text window{'s' if n_windows != 1 else ''})"
    return f"{base} (model score {score:.2f} over {n_windows} text windows)"


# ── Inference engine (lazy) ───────────────────────────────────────────────

def _get_engine(device: str = "cpu"):
    device = _normalize_device(device)
    if device not in _VALID_DEVICES:
        raise ValueError(f"Unsupported local AI-detection device: {device}")
    if device in _engines:
        return _engines[device]
    # Double-checked locking: under a cold-start batch, several worker threads
    # can reach here at once; without the lock each would load DeBERTa weights
    # (hundreds of MB) in parallel — a memory spike that defeats "load once".
    with _engine_lock:
        if device in _engines:
            return _engines[device]
        path = str(model_manager.model_path())
        onnx_file = model_manager.model_path() / "model.onnx"
        built = None
        if onnx_file.is_file():
            try:
                built = _OnnxEngine(path, str(onnx_file), device=device)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ONNX engine unavailable, falling back to torch: %s", exc)
        if built is None:
            built = _TorchEngine(path, device=device)
        _engines[device] = built
        return built


class _TorchEngine:
    """transformers + torch runtime for the desklib custom model."""

    def __init__(self, model_dir: str, device: str = "cpu"):
        import torch
        from transformers import AutoTokenizer, AutoConfig, AutoModel, PreTrainedModel
        import torch.nn as nn

        self.torch = torch
        self.device = torch.device(device)
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)

        class _DesklibModel(PreTrainedModel):
            config_class = AutoConfig

            @property
            def all_tied_weights_keys(self):
                return self._tied_weights_keys or {}

            def __init__(self, config):
                super().__init__(config)
                self.model = AutoModel.from_config(config)
                self.classifier = nn.Linear(config.hidden_size, 1)
                self.init_weights()

            @classmethod
            def from_pretrained(cls, model_dir, **kwargs):
                """Load with key remapping: checkpoint uses 'model.*' / 'deberta.*',
                our wrapper uses 'model.*' via AutoModel — remap 'deberta.*' → 'model.*'."""
                import torch
                from pathlib import Path
                from safetensors.torch import load_file

                # Load raw weights
                sf_path = Path(model_dir) / "model.safetensors"
                if sf_path.exists():
                    state_dict = load_file(str(sf_path))
                else:
                    pt_path = Path(model_dir) / "pytorch_model.bin"
                    state_dict = torch.load(str(pt_path), map_location="cpu")

                # Remap 'deberta.*' → 'model.*' to match our wrapper's structure
                remapped = {}
                for k, v in state_dict.items():
                    if k.startswith("deberta."):
                        remapped["model." + k[len("deberta."):]] = v
                    else:
                        remapped[k] = v

                from transformers import AutoConfig as _AutoConfig
                config = _AutoConfig.from_pretrained(model_dir)
                model = cls(config)
                missing, unexpected = model.load_state_dict(remapped, strict=False)
                model.eval()
                return model, {"missing_keys": missing, "unexpected_keys": unexpected}

            def forward(self, input_ids, attention_mask=None, **_):
                outputs = self.model(input_ids, attention_mask=attention_mask)
                last_hidden = outputs[0]
                mask = attention_mask.unsqueeze(-1).expand(last_hidden.size()).float()
                summed = torch.sum(last_hidden * mask, 1)
                counts = torch.clamp(mask.sum(1), min=1e-9)
                pooled = summed / counts
                return self.classifier(pooled)

        self._ai_index: Optional[int] = None
        _info = None
        try:
            self.model, _info = _DesklibModel.from_pretrained(
                model_dir, output_loading_info=True
            )
        except Exception:  # noqa: BLE001
            # Fall back to a standard sequence-classification head if the
            # installed model isn't the desklib custom architecture.
            from transformers import AutoModelForSequenceClassification
            self._std = AutoModelForSequenceClassification.from_pretrained(model_dir)
            self.model = None
            self._std.eval()
            self._std.to(self.device)
            num_labels = int(getattr(self._std.config, "num_labels", 1) or 1)
            if num_labels > 1:
                self._ai_index = _ai_positive_index(getattr(self._std.config, "id2label", None))
                if self._ai_index is None:
                    # Refuse to guess which class is "AI" — guessing can invert
                    # the score and flag human text as AI.
                    raise ValueError(
                        "Cannot determine the AI-positive class from the model's "
                        "id2label; refusing to guess. Use a single-logit detector "
                        "or a model with clearly labelled classes."
                    )
        else:
            # If the checkpoint didn't actually contain the classifier head,
            # loading with strict=False leaves it at random init and does not
            # raise. Refuse rather than fabricate scores.
            missing = set((_info or {}).get("missing_keys") or [])
            if any(k.startswith("classifier") for k in missing):
                raise ValueError(
                    "desklib classifier head missing from the checkpoint "
                    "(would score with a random head); refusing to run."
                )
            self.model.eval()
            self.model.to(self.device)
            self._std = None

    def score(self, text: str) -> float:
        torch = self.torch
        enc = self.tokenizer(
            text, truncation=True, max_length=_MAX_TOKENS, return_tensors="pt"
        )
        enc = {key: value.to(self.device) for key, value in enc.items()}
        with torch.no_grad():
            if self.model is not None:
                logit = self.model(enc["input_ids"], attention_mask=enc["attention_mask"])
                return float(torch.sigmoid(logit).squeeze().item())
            out = self._std(**enc).logits
            if out.shape[-1] == 1:
                return float(torch.sigmoid(out).squeeze().item())
            probs = torch.softmax(out, dim=-1).squeeze()
            return float(probs[self._ai_index].item())


class _OnnxEngine:
    """onnxruntime runtime (used only if a model.onnx with a head exists)."""

    def __init__(self, model_dir: str, onnx_path: str, device: str = "cpu"):
        import onnxruntime as ort
        from transformers import AutoTokenizer, AutoConfig
        import numpy as np

        self.np = np
        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        if device == "cuda":
            if "CUDAExecutionProvider" not in ort.get_available_providers():
                raise RuntimeError("ONNX Runtime CUDA provider is not available")
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(onnx_path, providers=providers)
        self.input_names = {i.name for i in self.session.get_inputs()}
        # Resolve the AI-positive class index from the config for multi-class
        # heads (single-logit heads use sigmoid and ignore this).
        self._ai_index: Optional[int] = None
        try:
            cfg = AutoConfig.from_pretrained(model_dir)
            if int(getattr(cfg, "num_labels", 1) or 1) > 1:
                self._ai_index = _ai_positive_index(getattr(cfg, "id2label", None))
        except Exception:  # noqa: BLE001
            self._ai_index = None

    def score(self, text: str) -> float:
        np = self.np
        enc = self.tokenizer(
            text, truncation=True, max_length=_MAX_TOKENS, return_tensors="np"
        )
        feeds = {k: v for k, v in enc.items() if k in self.input_names}
        out = self.session.run(None, feeds)[0]
        arr = np.asarray(out).reshape(-1)
        if arr.size == 1:
            return float(1.0 / (1.0 + np.exp(-arr[0])))
        if self._ai_index is None:
            raise ValueError(
                "Multi-class ONNX detector has no resolvable AI-positive class; "
                "refusing to guess which logit means 'AI'."
            )
        e = np.exp(arr - arr.max())
        return float((e / e.sum())[self._ai_index])
