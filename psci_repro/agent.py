"""Agent configuration: Opus 4.7 draft + Claude Agent SDK audit session.

This is the study's harness code reduced to the configuration reported in the paper
("audit" mode, override threshold 2, no judge, no revise). Other experimental modes were removed.

For each image:
  Stage A: one Messages call with the Xu Model 5 prompt (same request as the Opus
    baseline, under a different cache key) -> draft rating.
  Stage B: one headless Agent SDK session, working directory `harness/`, which auto-loads
    `harness/.claude/` (CLAUDE.md, 4 sub-agents, 5 skills) and gets the 6 MCP tools from
    `tools.py`. The session is told to ratify the draft unless it finds evidence for a change
    of at least `audit_threshold` levels, and commits its rating via `emit_rating`.
  Final rating = the emitted rating (the draft if nothing was emitted).
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    ToolUseBlock,
    create_sdk_mcp_server,
    query,
)

from . import api, tools as tools_mod, xu
from .runs import parse_rating

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_DIR = REPO_ROOT / "harness"


def run_agent_session(*, cell_id: str, image_path: Path, image_id: int, replicate: int, cell_config: dict) -> dict:
    return asyncio.run(_run_agent_session_async(
        cell_id=cell_id, image_path=image_path, image_id=image_id, replicate=replicate, cell_config=cell_config,
    ))


async def _run_agent_session_async(*, cell_id: str, image_path: Path, image_id: int, replicate: int, cell_config: dict) -> dict:
    audit_threshold = int(cell_config["audit_threshold"])
    max_agent_turns = int(cell_config["max_agent_turns"])

    metas: list[dict] = []
    draft_int, draft_rationale, draft_meta = _run_holistic_draft(
        cell_id=cell_id, image_path=image_path, image_id=image_id, replicate=replicate, cell_config=cell_config,
    )
    metas.append(draft_meta)

    sdk_pass = await _run_one_agent_pass(
        cell_id=cell_id,
        image_id=image_id,
        replicate=replicate,
        cell_config=cell_config,
        max_turns=max_agent_turns,
        seed_prompt=_audit_prompt(
            image_path=image_path, draft_int=draft_int, draft_rationale=draft_rationale, audit_threshold=audit_threshold,
        ),
        pass_label="lead",
    )
    metas.extend(sdk_pass["metas"])
    emit = sdk_pass["emit"] or {}
    audit_int = emit.get("rating_int_1_10")

    final_rating = audit_int if audit_int is not None else draft_int
    override_fired = draft_int is not None and audit_int is not None and int(audit_int) != int(draft_int)

    return {
        "cell": cell_id,
        "image_id": image_id,
        "replicate": replicate,
        "rating": final_rating,
        "draft_int": draft_int,
        "audit_int": audit_int,
        "override_fired": override_fired,
        "rationale_text": emit.get("rationale_text", "") or draft_rationale,
        "distresses_observed": emit.get("distresses_observed", []),
        "severities": emit.get("severities", {}),
        "tool_calls_log": sdk_pass["tool_calls_log"],
        "parse_failed": final_rating is None,
        "meta": metas,
    }


def _run_holistic_draft(*, cell_id: str, image_path: Path, image_id: int, replicate: int, cell_config: dict) -> tuple[int | None, str, dict]:
    prompt = xu.model5_prompt()
    b64, media_type = api.encode_image(image_path)
    user_content = [api.text_block(t) for t in prompt["before"]]
    user_content.append(api.image_block(b64, media_type))
    user_content += [api.text_block(t) for t in prompt["after"]]

    response, meta = api.call_messages(
        cell=cell_id,
        image_id=image_id,
        replicate=replicate,
        step="holistic_draft",
        system=prompt["system"],
        messages=[{"role": "user", "content": user_content}],
        max_tokens=int(cell_config["draft_max_tokens"]),
        temperature=0.0,
        thinking_budget=0,
    )
    raw_text = next((b.text for b in response.content if getattr(b, "type", None) == "text"), "")
    return parse_rating(raw_text), (raw_text.strip() if raw_text else ""), meta


async def _run_one_agent_pass(
    *, cell_id: str, image_id: int, replicate: int, cell_config: dict, max_turns: int, seed_prompt: str, pass_label: str,
) -> dict:
    """Run one SDK query() session; return the emit_rating payload, per-session metas, and tool-call log."""
    emit_file = Path(tempfile.mkstemp(prefix=f"emit_{cell_id}_{image_id}_{replicate}_{pass_label}_", suffix=".json")[1])
    try:
        os.environ["EMIT_RATING_RESULT_PATH"] = str(emit_file)
        tools_mod.reset_last_emit()

        pavement_server = create_sdk_mcp_server(name="pavement", version="2.0.0", tools=tools_mod.ALL_TOOLS)
        allowed_tools = ["Read", "Bash", "Glob", "Grep", "Edit", "Write", "Skill"]
        if cell_config["sub_agents"]:
            allowed_tools += ["Agent", "Task"]
        allowed_tools += [f"mcp__pavement__{t}" for t in cell_config["tools"]]

        options = ClaudeAgentOptions(
            model=cell_config["model_id"],
            cwd=str(HARNESS_DIR),
            allowed_tools=allowed_tools,
            mcp_servers={"pavement": pavement_server},
            permission_mode="acceptEdits",
            max_turns=max_turns,
            setting_sources=["project"],  # loads harness/.claude/ (CLAUDE.md, agents/, skills/)
        )

        t0 = time.time()
        tool_calls_log: list[dict] = []
        metas: list[dict] = []
        turn_idx = 0
        async for msg in query(prompt=seed_prompt, options=options):
            turn_idx += 1
            if isinstance(msg, AssistantMessage):
                for block in (msg.content or []):
                    if isinstance(block, ToolUseBlock):
                        inp = block.input if isinstance(block.input, dict) else {}
                        sat = (inp.get("subagent_type") or inp.get("agent")) if block.name in {"Agent", "Task"} else None
                        tool_calls_log.append({
                            "turn": turn_idx,
                            "name": block.name,
                            "input": _shallow_safe_input(inp),
                            "subagent_type": sat,
                        })
            elif isinstance(msg, ResultMessage):
                metas.append(_meta_from_result(msg, cell_id, image_id, replicate, pass_label))

        emit_payload: dict | None = None
        if emit_file.exists():
            try:
                emit_payload = json.loads(emit_file.read_text())
            except (OSError, json.JSONDecodeError):
                emit_payload = None
        if emit_payload is None:
            emit_payload = tools_mod.get_last_emit()

        if metas and "wall_clock_s" not in metas[-1]:
            metas[-1]["wall_clock_s"] = round(time.time() - t0, 2)
        return {"emit": emit_payload, "metas": metas, "tool_calls_log": tool_calls_log}
    finally:
        try:
            if emit_file.exists():
                emit_file.unlink()
        except OSError:
            pass
        os.environ.pop("EMIT_RATING_RESULT_PATH", None)


def _shallow_safe_input(inp: dict) -> dict:
    out: dict[str, Any] = {}
    for k, v in (inp or {}).items():
        if isinstance(v, str) and len(v) > 500:
            out[k] = v[:500] + f"... [truncated, total {len(v)} chars]"
        elif isinstance(v, list) and len(v) > 20:
            out[k] = v[:20] + [f"... [truncated, total {len(v)} items]"]
        else:
            out[k] = v
    return out


def _meta_from_result(msg: ResultMessage, cell_id: str, image_id: int, replicate: int, step: str) -> dict:
    usage = msg.usage or {}
    return {
        "model_id": "claude-opus-4-7",
        "model_version_string": "claude-opus-4-7",
        "provider": "anthropic",
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "latency_s": round((msg.duration_ms or 0) / 1000.0, 3),
        "cost_usd": round(msg.total_cost_usd or 0.0, 6),  # as reported by the Agent SDK
        "stop_reason": msg.stop_reason or "",
        "cell": cell_id,
        "image_id": image_id,
        "replicate": replicate,
        "step": f"agent.{step}",
        "num_turns": msg.num_turns,
    }


def _audit_prompt(*, image_path: Path, draft_int: int | None, draft_rationale: str, audit_threshold: int) -> str:
    """Audit-mode lead prompt: review the draft, ratify by default, override only on
    >= audit_threshold-level evidence. The threshold is stated in this prompt; the runner
    does not clamp the emitted rating."""
    return (
        "A senior pavement engineer issued the following draft PSCI rating from a holistic "
        "view of this image, without tool support:\n\n"
        f"  draft_rating: {draft_int}\n"
        f"  draft_rationale: {draft_rationale}\n\n"
        "Your job is NOT to re-rate the image from scratch. Your job is to AUDIT this draft.\n\n"
        f"IMAGE PATH: {image_path}\n\n"
        "Workflow:\n"
        "  1. Read the image with the `Read` tool.\n"
        "  2. Sub-agents available via the `Agent` tool: `distress-detector`, `severity-rater`, "
        "`coverage-estimator`, `band-checker`. Use them and the MCP tools "
        "(`mcp__pavement__compute_distress_coverage`, `mcp__pavement__psci_rubric_lookup`, "
        "`mcp__pavement__distress_taxonomy_crosswalk`, `mcp__pavement__list_band_signatures`, "
        "`mcp__pavement__read_manual_section`) to gather specific evidence about visible "
        "distresses, severities, and coverage.\n"
        "  3. Compare the evidence to the draft. Your DEFAULT action is to RATIFY: call "
        f"`mcp__pavement__emit_rating` with rating_int_1_10={draft_int} and a 1-2 sentence "
        "ratification summary that names the key evidence supporting the draft.\n"
        f"  4. OVERRIDE only when the evidence contradicts the draft by ≥{audit_threshold} PSCI levels "
        "AND you can cite specific distress evidence the holistic call missed. Then call "
        "`mcp__pavement__emit_rating` with the new integer rating and an evidence_rationale that "
        "names what the holistic call missed.\n\n"
        f"The bar for overriding is HIGH (≥{audit_threshold} levels). The holistic call from your "
        "same model has good PSCI priors; tool-mediated decomposition tends to regress toward the "
        "middle of the scale. Do not override on intuition or aggregate-coverage estimates alone — "
        "you must point to a specific distress, with a specific severity, that the draft rationale "
        "did not consider.\n\n"
        "Call `emit_rating` exactly once when done. The session ends after that call."
    )
