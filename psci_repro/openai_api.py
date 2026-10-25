"""OpenAI Chat Completions wrapper with on-disk response caching (as used in the study).

Used for the gpt-4o baseline (vision) and for the GPT-5.5 judge of the contamination probe.
"""

from __future__ import annotations

import base64
import hashlib
import json
import time
from pathlib import Path
from typing import Any

from openai import OpenAI

from .api import CACHE_DIR, hash_request

JUDGE_MODEL = "gpt-5.5-2026-04-23"

# USD per million tokens used to estimate `cost_usd`; an estimate, not a billed amount.
_PRICING_BY_MODEL: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    JUDGE_MODEL: (1.25, 10.00),
}

_client: OpenAI | None = None


def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI()
    return _client


def extract_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    msg = getattr(choices[0], "message", None)
    return ((getattr(msg, "content", "") if msg is not None else "") or "").strip()


def _usage_meta(raw: dict, model: str) -> dict:
    usage = raw.get("usage") or {}
    in_tok = int(usage.get("prompt_tokens", 0) or 0)
    out_tok = int(usage.get("completion_tokens", 0) or 0)
    details = usage.get("completion_tokens_details") or {}
    reasoning_tok = int(details.get("reasoning_tokens", 0) or 0) if isinstance(details, dict) else 0
    p_in, p_out = _PRICING_BY_MODEL[model]
    choices = raw.get("choices") or []
    return {
        "model_id": model,
        "model_version_string": raw.get("model", model),
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "reasoning_tokens": reasoning_tok,
        "cost_usd": round((in_tok / 1_000_000) * p_in + (out_tok / 1_000_000) * p_out, 6),
        "stop_reason": (choices[0].get("finish_reason") or "") if choices and isinstance(choices[0], dict) else "",
    }


def _cached(payload: dict) -> tuple[str, Path, tuple[Any, dict] | None]:
    h = hash_request(payload)
    path = CACHE_DIR / f"{h}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        return h, path, (_rehydrate(cached["raw_response"]), cached["meta"])
    return h, path, None


def _store(path: Path, raw: dict, meta: dict) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps({"raw_response": raw, "meta": meta}, indent=2))


def call_chat(
    *,
    cell: str,
    image_id: int,
    replicate: int,
    step: str,
    system: str,
    user_text: str,
    response_format: dict[str, Any] | None,
    max_output_tokens: int,
    reasoning_effort: str,
    extra_cache_keys: dict[str, Any] | None = None,
) -> tuple[Any, dict]:
    """Text-only call to the judge model."""
    payload = {
        "provider": "openai",
        "model": JUDGE_MODEL,
        "system": system,
        "user_text": user_text,
        "response_format": response_format,
        "max_output_tokens": max_output_tokens,
        "reasoning_effort": reasoning_effort,
        "cell": cell,
        "image_id": image_id,
        "replicate": replicate,
        "step": step,
        **(extra_cache_keys or {}),
    }
    h, path, hit = _cached(payload)
    if hit:
        return hit

    kwargs: dict[str, Any] = {
        "model": JUDGE_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user_text}],
        "max_completion_tokens": max_output_tokens,
        "reasoning_effort": reasoning_effort,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    t0 = time.time()
    response = client().chat.completions.create(**kwargs)
    latency = time.time() - t0

    raw = response.model_dump()
    meta = {**_usage_meta(raw, JUDGE_MODEL), "latency_s": round(latency, 3), "cell": cell,
            "image_id": image_id, "replicate": replicate, "step": step, "request_hash": h}
    _store(path, raw, meta)
    return response, meta


def call_chat_vision(
    *,
    cell: str,
    image_id: int,
    replicate: int,
    step: str,
    model_id: str,
    system: str,
    user_text: str,
    image_path: Path,
    max_tokens: int,
    temperature: float,
) -> tuple[Any, dict]:
    """Vision call: one text part followed by the image (media type from the file extension)."""
    image_bytes = image_path.read_bytes()
    payload = {
        "provider": "openai",
        "kind": "vision",
        "model": model_id,
        "system": system,
        "user_text": user_text,
        "image_bytes_hash": hashlib.sha256(image_bytes).hexdigest()[:32],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "reasoning_effort": None,
        "cell": cell,
        "image_id": image_id,
        "replicate": replicate,
        "step": step,
    }
    h, path, hit = _cached(payload)
    if hit:
        return hit

    suffix = image_path.suffix.lower()
    media_type = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png" if suffix == ".png" else None
    if media_type is None:
        raise ValueError(f"unsupported image extension: {image_path}")
    data_url = f"data:{media_type};base64,{base64.standard_b64encode(image_bytes).decode('ascii')}"
    kwargs: dict[str, Any] = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": user_text},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
        "max_completion_tokens": max_tokens,
        "temperature": temperature,
    }
    t0 = time.time()
    response = client().chat.completions.create(**kwargs)
    latency = time.time() - t0

    raw = response.model_dump()
    meta = {**_usage_meta(raw, model_id), "provider": "openai", "latency_s": round(latency, 3), "cell": cell,
            "image_id": image_id, "replicate": replicate, "step": step, "request_hash": h}
    _store(path, raw, meta)
    return response, meta


def _rehydrate(raw: dict) -> Any:
    from types import SimpleNamespace

    def to_ns(obj):
        if isinstance(obj, dict):
            return SimpleNamespace(**{k: to_ns(v) for k, v in obj.items()})
        if isinstance(obj, list):
            return [to_ns(x) for x in obj]
        return obj

    return to_ns(raw)
