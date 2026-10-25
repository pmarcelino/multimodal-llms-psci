"""Contamination (recall) probe: four questions per image to Opus 4.7, graded 0-3 by GPT-5.5.

Prompts, settings and grading are those of the run behind results/contamination_probe.jsonl.
Each question is an independent call (no shared history). The judge sees only the question
and the response, never the image.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from . import api, openai_api, xu

REPO_ROOT = Path(__file__).resolve().parents[1]

PROBE_MAX_TOKENS = 400
JUDGE_MAX_OUTPUT_TOKENS = 4000

PROBE_SYSTEM = (
    "You are participating in a controlled training-data recognition study. "
    "Answer based on what you actually recall, not what you can infer from image content. "
    "If you have no specific recall, say so explicitly. Do not refuse to answer; "
    "responding with honest non-recall is the correct behaviour when you have no memory of the image."
)

PROBE_QUESTIONS: dict[str, str] = {
    # Q1: direct recognition
    "q1": (
        "Have you seen this exact image during training? "
        "Reply only: Yes / No / Maybe, followed by confidence 0-100."
    ),
    # Q2: source attribution
    "q2": (
        "What is the source of this image? "
        "Identify any dataset, paper, repository, website, or original publication you can recall."
    ),
    # Q3: label leakage
    "q3": (
        "If this image is part of a labeled dataset, "
        "what label, rating, or category is attached to it in its source?"
    ),
    # Q4: free-form recall
    "q4": (
        "Tell me anything else you recall about this image — "
        "captions, neighboring images, context, or surrounding text in its source."
    ),
}

PROBE_STEP_NAMES = {"q1": "q1_recognize", "q2": "q2_source", "q3": "q3_label", "q4": "q4_freeform"}

JUDGE_SYSTEM = (
    "You are a strict but fair grader for a training-data contamination probe. "
    "Given a model's response to a recognition question about an image from "
    "Xu Dataset 1 (a public PSCI pavement-rating dataset whose source images derive from "
    "Mullaney 2014 and Qureshi 2023), assign a contamination level 0-3 according to the rubric. "
    "Output ONLY a single JSON object: "
    '{"level": <0|1|2|3>, "rationale": "<one-sentence justification>"}. '
    "No prose before or after."
)

JUDGE_USER_TEMPLATE = """Probe question asked: {question_text}

Model response:
\"\"\"
{response_text}
\"\"\"

Contamination ladder:
- Level 0 (none): Explicit non-recall ("I don't recall this image"), refusal,
  or purely content-based description ("a road with cracks") with no claim of source.
- Level 1 (related literature): Acknowledges the broad domain ("civil engineering",
  "pavement condition") but names no specific dataset, paper, or repository.
- Level 2 (dataset family): Names a plausibly-related dataset, paper, rubric, or
  organisation without exact attribution. Examples: "PSCI manual", "Mullaney",
  "Qureshi", "pavement condition index dataset", "asphalt distress benchmark".
- Level 3 (exact attribution): Names Xu et al. 2025, Mullaney 2014, Qureshi 2023,
  the github.com/xushuoshuoxss/zero-shot-psci-llm-prompts repository, or recovers a
  PSCI level (1-10) consistent with a labeled dataset.

Rules:
- Score on what the response claims to RECALL, not on whether the model is right.
- A confident "No, I have not seen this" → level 0.
- A "Maybe" with no naming → level 0 or 1 depending on whether literature is named.
- "I cannot determine training-data inclusion" without further detail → level 0.
- If the response names two levels worth of evidence, score the HIGHER one.

Output the JSON object only."""

JUDGE_RESPONSE_SCHEMA: dict = {
    "type": "json_schema",
    "json_schema": {
        "name": "contamination_grade",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "level": {"type": "integer", "enum": [0, 1, 2, 3]},
                "rationale": {"type": "string"},
            },
            "required": ["level", "rationale"],
            "additionalProperties": False,
        },
    },
}


def _media_type(raw: bytes) -> str:
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if raw.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    raise ValueError(f"unsupported image content: magic={raw[:8]!r}")


def run_probe(*, image_path: Path, image_id: int, question: str, replicate: int = 0) -> dict:
    raw = image_path.read_bytes()
    response, meta = api.call_messages(
        cell="probe",
        image_id=image_id,
        replicate=replicate,
        step=PROBE_STEP_NAMES[question],
        system=PROBE_SYSTEM,
        messages=[{
            "role": "user",
            "content": [
                api.image_block(base64.standard_b64encode(raw).decode("ascii"), _media_type(raw)),
                api.text_block(PROBE_QUESTIONS[question]),
            ],
        }],
        max_tokens=PROBE_MAX_TOKENS,
        temperature=0.0,
        thinking_budget=0,
        extra_cache_keys={"image_set": "xu_dataset_1", "stage": "probe"},
    )
    text = "\n".join(getattr(b, "text", "") or "" for b in (response.content or []) if getattr(b, "type", None) == "text")
    return {"response_text": text.strip(), "meta": meta}


def _parse_judge_output(raw: str) -> tuple[int, str]:
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    brace = re.search(r"\{.*\}", text, re.DOTALL)
    if brace:
        text = brace.group(0)
    obj = json.loads(text)
    level = int(obj["level"])
    if level not in {0, 1, 2, 3}:
        raise ValueError(f"judge level {level} outside 0-3: {obj!r}")
    return level, str(obj.get("rationale", "")).strip()


def grade_response(*, response_text: str, image_id: int, question: str, replicate: int = 0) -> dict:
    response, meta = openai_api.call_chat(
        cell="probe_judge",
        image_id=image_id,
        replicate=replicate,
        step=f"judge_{question}",
        system=JUDGE_SYSTEM,
        user_text=JUDGE_USER_TEMPLATE.format(question_text=PROBE_QUESTIONS[question], response_text=response_text),
        response_format=JUDGE_RESPONSE_SCHEMA,
        max_output_tokens=JUDGE_MAX_OUTPUT_TOKENS,
        reasoning_effort="none",
        extra_cache_keys={
            "image_set": "xu_dataset_1",
            "stage": "probe_judge",
            "response_sha": hashlib.sha256(response_text.encode("utf-8")).hexdigest()[:16],
        },
    )
    level, rationale = _parse_judge_output(openai_api.extract_text(response))
    return {"contamination_level": level, "judge_rationale": rationale, "judge_model": meta["model_id"]}


def run(output_dir: Path | None, image_ids: list[int] | None) -> Path:
    """Probe and grade Xu Dataset 1 images; write contamination_probe.jsonl and print Table I's Xu row."""
    xu.require()
    output_dir = output_dir or REPO_ROOT / "results" / f"rerun_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}"
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "contamination_probe.jsonl"
    done = set()
    if out_path.exists():
        done = {(r["image_id"], r["probe_question"]) for r in map(json.loads, out_path.read_text().splitlines())}

    with out_path.open("a") as f:
        for image_id in image_ids or xu.image_ids():
            path = xu.image_path(image_id)
            for q in PROBE_QUESTIONS:
                if (image_id, q) in done:
                    continue
                probe = run_probe(image_path=path, image_id=image_id, question=q)
                grade = grade_response(response_text=probe["response_text"], image_id=image_id, question=q)
                row = {
                    "image_id": image_id,
                    "image_set": "xu_dataset_1",
                    "filename": path.name,
                    "probe_question": q,
                    "replicate": 0,
                    "response_text": probe["response_text"],
                    **grade,
                    "model_id": probe["meta"]["model_id"],
                    "input_tokens": probe["meta"]["input_tokens"],
                    "output_tokens": probe["meta"]["output_tokens"],
                }
                f.write(json.dumps(row) + "\n")
                f.flush()
                print(f"  image {image_id:2d} {q}: level {grade['contamination_level']}", flush=True)

    rows = [json.loads(line) for line in out_path.read_text().splitlines() if line.strip()]
    per_image: dict[int, int] = defaultdict(int)
    for r in rows:
        per_image[r["image_id"]] = max(per_image[r["image_id"]], r["contamination_level"])
    dist = Counter(per_image.values())
    print(f"\nPer-image maximum level over {len(per_image)} images: "
          + "  ".join(f"L{lvl}={dist.get(lvl, 0)}" for lvl in range(4)))
    return output_dir
