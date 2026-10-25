"""The three configurations and the run loop that writes result JSONL.

Configuration settings are those of the runs behind results/*.jsonl.
"""

from __future__ import annotations

import json
import signal
import time
from datetime import datetime, timezone
from pathlib import Path

from . import api, openai_api, xu

REPO_ROOT = Path(__file__).resolve().parents[1]

CONFIGS: dict[str, dict] = {
    # Xu Model 5 prompt on the bare gpt-4o alias, 10 replicates per image.
    "gpt4o": {
        "cell_id": "gpt4o",
        "model_id": "gpt-4o",
        "max_tokens": 300,
        "temperature": 0.0,
        "replicates": 10,
        "output": "gpt4o_baseline.jsonl",
    },
    # Same prompt on Claude Opus 4.7 (temperature parameter omitted; the model rejects it).
    "opus": {
        "cell_id": "opus",
        "model_id": "claude-opus-4-7",
        "max_tokens": 300,
        "replicates": 1,
        "output": "opus_baseline.jsonl",
    },
    # Opus 4.7 draft + Agent SDK audit session (see agent.py).
    "agent": {
        "cell_id": "agent",
        "model_id": "claude-opus-4-7",
        "draft_max_tokens": 300,
        "max_agent_turns": 60,
        "audit_threshold": 2,
        "sub_agents": ["distress-detector", "severity-rater", "coverage-estimator", "band-checker"],
        "tools": [
            "compute_distress_coverage",
            "psci_rubric_lookup",
            "distress_taxonomy_crosswalk",
            "list_band_signatures",
            "read_manual_section",
            "emit_rating",
        ],
        "replicates": 1,
        "output": "opus_agent.jsonl",
    },
}

PER_ROW_TIMEOUT_S = 360
AGENT_ATTEMPTS = 3


def parse_rating(text: str) -> int | None:
    """Xu's int(response) parser, tolerant of trailing punctuation or wrappers."""
    import re

    text = (text or "").strip()
    try:
        return int(text)
    except ValueError:
        m = re.search(r"\b([1-9]|10)\b", text)
        return int(m.group(1)) if m else None


def _first_text(response) -> str:
    return next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")


def run_gpt4o(image_path: Path, image_id: int, replicate: int, cfg: dict) -> dict:
    prompt = xu.model5_prompt()
    # The gpt-4o calls send the user text parts as one text block, then the image.
    user_text = "".join(prompt["before"]) + "\n" + "".join(prompt["after"])
    response, meta = openai_api.call_chat_vision(
        cell=cfg["cell_id"], image_id=image_id, replicate=replicate, step="single_call",
        model_id=cfg["model_id"], system=prompt["system"], user_text=user_text, image_path=image_path,
        max_tokens=cfg["max_tokens"], temperature=cfg["temperature"],
    )
    rating = parse_rating(openai_api.extract_text(response))
    return {"rating": rating, "parse_failed": rating is None, "meta": [meta]}


def run_opus(image_path: Path, image_id: int, replicate: int, cfg: dict) -> dict:
    prompt = xu.model5_prompt()
    b64, media_type = api.encode_image(image_path)
    content = [api.text_block(t) for t in prompt["before"]]
    content.append(api.image_block(b64, media_type))
    content += [api.text_block(t) for t in prompt["after"]]
    response, meta = api.call_messages(
        cell=cfg["cell_id"], image_id=image_id, replicate=replicate, step="single_call",
        system=prompt["system"], messages=[{"role": "user", "content": content}],
        max_tokens=cfg["max_tokens"], temperature=0.0, thinking_budget=0,
    )
    rating = parse_rating(_first_text(response))
    return {"rating": rating, "parse_failed": rating is None, "meta": [meta]}


def run_agent(image_path: Path, image_id: int, replicate: int, cfg: dict) -> dict:
    from .agent import run_agent_session

    last_err: Exception | None = None
    for attempt in range(AGENT_ATTEMPTS):
        try:
            return run_agent_session(
                cell_id=cfg["cell_id"], image_path=image_path, image_id=image_id, replicate=replicate, cell_config=cfg,
            )
        except TimeoutError:
            raise  # the per-row deadline (SIGALRM) is one-shot; retrying would run without it
        except Exception as e:  # SDK sessions can fail transiently; retry, then record a failed row
            last_err = e
            print(f"  WARN: agent session for image {image_id} attempt {attempt + 1}/{AGENT_ATTEMPTS} failed: {e}", flush=True)
    return {"rating": None, "parse_failed": True, "rationale_text": f"agent session failed: {last_err}", "meta": []}


RUNNERS = {"gpt4o": run_gpt4o, "opus": run_opus, "agent": run_agent}


def _public_row(config: str, image_id: int, replicate: int, raw: dict) -> dict:
    """Convert a runner row to the schema of results/*.jsonl."""
    metas = raw.get("meta", [])
    row = {
        "image_id": image_id,
        "replicate": replicate,
        "parse_failed": raw["parse_failed"],
        "model_id": CONFIGS[config]["model_id"],
        "model_version": metas[0].get("model_version_string") if metas else None,
        "input_tokens": sum(m.get("input_tokens", 0) for m in metas),
        "output_tokens": sum(m.get("output_tokens", 0) for m in metas),
        "latency_s": round(sum(m.get("latency_s", 0.0) for m in metas), 3),
        "cost_usd": round(sum(m.get("cost_usd", 0.0) for m in metas), 6),
    }
    if config == "agent":
        log = json.loads(json.dumps(raw.get("tool_calls_log", [])).replace(str(REPO_ROOT) + "/", ""))
        row.update(
            draft_rating=raw.get("draft_int"),
            agent_rating=raw["rating"],
            override_fired=raw.get("override_fired", False),
            distresses_observed=raw.get("distresses_observed", []),
            severities=raw.get("severities", {}),
            rationale_text=raw.get("rationale_text", ""),
            tool_calls_log=log,
        )
    else:
        row["rating"] = raw["rating"]
    return row


def _done_keys(path: Path) -> set[tuple[int, int]]:
    """(image_id, replicate) pairs already written with a rating; failed rows are retried."""
    if not path.exists():
        return set()
    keys = set()
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if not r["parse_failed"]:
                keys.add((r["image_id"], r["replicate"]))
    return keys


def run(configs: list[str], output_dir: Path | None, image_ids: list[int] | None, replicates: int | None) -> Path:
    xu.require()
    output_dir = output_dir or REPO_ROOT / "results" / f"rerun_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    output_dir.mkdir(parents=True, exist_ok=True)
    ids = image_ids or xu.image_ids()
    labels = xu.labels()

    for config in configs:
        cfg = CONFIGS[config]
        reps = replicates or cfg["replicates"]
        out_path = output_dir / cfg["output"]
        done = _done_keys(out_path)
        print(f"\n=== {config}: {len(ids)} images x {reps} replicate(s) -> {out_path}")
        with out_path.open("a") as f:
            for image_id in ids:
                for rep in range(reps):
                    if (image_id, rep) in done:
                        continue
                    t0 = time.time()

                    def _timeout(signum, frame):
                        raise TimeoutError(f"row exceeded {PER_ROW_TIMEOUT_S}s")

                    old = signal.signal(signal.SIGALRM, _timeout)
                    signal.alarm(PER_ROW_TIMEOUT_S)
                    try:
                        raw = RUNNERS[config](xu.image_path(image_id), image_id, rep, cfg)
                    except TimeoutError as e:
                        raw = {"rating": None, "parse_failed": True, "rationale_text": str(e), "meta": []}
                    finally:
                        signal.alarm(0)
                        signal.signal(signal.SIGALRM, old)
                    row = _public_row(config, image_id, rep, raw)
                    f.write(json.dumps(row) + "\n")
                    f.flush()
                    rating = row.get("agent_rating", row.get("rating"))
                    extra = f" draft={row['draft_rating']}" if config == "agent" else ""
                    print(f"  image {image_id:2d} rep {rep}:{extra} rating={rating} label={labels[image_id]} "
                          f"cost=${row['cost_usd']:.4f} ({time.time() - t0:.1f}s)", flush=True)
    return output_dir
