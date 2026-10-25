"""Anthropic Messages wrapper with on-disk response caching (as used in the study)."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from anthropic import Anthropic

REPO_ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = REPO_ROOT / ".cache"

MODEL_ID = "claude-opus-4-7"
# USD per million tokens used to estimate `cost_usd`; an estimate, not a billed amount.
PRICE_INPUT_PER_MTOK = 15.0
PRICE_OUTPUT_PER_MTOK = 75.0

_client: Anthropic | None = None


def client() -> Anthropic:
    global _client
    if _client is None:
        _client = Anthropic()
    return _client


def encode_image(image_path: Path) -> tuple[str, str]:
    """Return (base64_data, media_type), detecting the media type from magic bytes.

    Xu Dataset 1 image 37 has PNG bytes behind a .jpg extension."""
    raw = image_path.read_bytes()
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type = "image/png"
    elif raw.startswith(b"\xff\xd8\xff"):
        media_type = "image/jpeg"
    elif image_path.suffix.lower() in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"
    elif image_path.suffix.lower() == ".png":
        media_type = "image/png"
    else:
        raise ValueError(f"unsupported image: {image_path}")
    return base64.standard_b64encode(raw).decode("ascii"), media_type


def hash_request(payload: dict[str, Any]) -> str:
    serialised = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(serialised).hexdigest()[:32]


def call_messages(
    *,
    cell: str,
    image_id: int,
    replicate: int,
    step: str,
    system: str | list,
    messages: list,
    max_tokens: int = 2000,
    temperature: float = 0.0,
    thinking_budget: int = 0,
    extra_cache_keys: dict[str, Any] | None = None,
) -> tuple[Any, dict]:
    """One Messages call, cached on disk under .cache/ keyed on the full request payload.

    claude-opus-4-7 rejects the `temperature` parameter, so it is omitted for that model
    (requests with temperature > 0 are refused rather than silently run at the default).
    """
    payload = {
        "model": MODEL_ID,
        "system": system,
        "messages": messages,
        "tools": [],
        "tool_choice": None,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "thinking_budget": thinking_budget,
        "cell": cell,
        "image_id": image_id,
        "replicate": replicate,
        "step": step,
        **(extra_cache_keys or {}),
    }
    h = hash_request(payload)
    cache_path = CACHE_DIR / f"{h}.json"
    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        return _rehydrate(cached["raw_response"]), cached["meta"]

    t0 = time.time()
    kwargs: dict[str, Any] = {"model": MODEL_ID, "system": system, "messages": messages, "max_tokens": max_tokens}
    if thinking_budget > 0:
        if thinking_budget < 1024:
            raise ValueError(f"thinking_budget must be >= 1024 tokens (got {thinking_budget})")
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": thinking_budget}
    elif not MODEL_ID.startswith("claude-opus-4-7"):
        kwargs["temperature"] = temperature
    elif temperature > 0.0:
        raise NotImplementedError(f"{MODEL_ID} does not accept temperature; refusing T={temperature}")
    response = client().messages.create(**kwargs)
    latency = time.time() - t0

    raw = response.model_dump()
    in_tok = response.usage.input_tokens
    out_tok = response.usage.output_tokens
    cost_usd = (in_tok / 1_000_000) * PRICE_INPUT_PER_MTOK + (out_tok / 1_000_000) * PRICE_OUTPUT_PER_MTOK
    meta = {
        "model_id": MODEL_ID,
        "model_version_string": raw.get("model", MODEL_ID),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "latency_s": round(latency, 3),
        "cost_usd": round(cost_usd, 6),
        "stop_reason": response.stop_reason,
        "cell": cell,
        "image_id": image_id,
        "replicate": replicate,
        "step": step,
        "request_hash": h,
    }
    CACHE_DIR.mkdir(exist_ok=True)
    cache_path.write_text(json.dumps({"raw_response": raw, "meta": meta}, indent=2))
    return response, meta


def _rehydrate(raw: dict) -> Any:
    """Replay a cached response as a SimpleNamespace tree exposing .content, .stop_reason, .usage."""
    from types import SimpleNamespace

    def to_ns(obj):
        if isinstance(obj, dict):
            return SimpleNamespace(**{k: to_ns(v) for k, v in obj.items()})
        if isinstance(obj, list):
            return [to_ns(x) for x in obj]
        return obj

    return to_ns(raw)


def image_block(b64_data: str, media_type: str) -> dict:
    return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64_data}}


def text_block(text: str) -> dict:
    return {"type": "text", "text": text}
