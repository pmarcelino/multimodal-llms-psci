"""Python tools for the agent harness (Claude Agent SDK, in-process MCP server).

Each tool is a Python async function decorated with `@claude_agent_sdk.tool(...)`. Tools are
exposed to the agent as an in-process MCP server (created via `create_sdk_mcp_server` in
agent.py) at `mcp__pavement__<tool_name>`.

Tools are deliberately *computational*, not knowledge-retrieval (knowledge lives in skills).
The agent calls these when measurement / lookup / authoritative reference would aid the
decision — e.g., compute polygon area as a percentage; look up the manual's text for one PSCI
rating; cross-reference an LTPP distress term to PSCI vocabulary.

Tool results are JSON-serialisable dicts (per the SDK convention) wrapped in
`{"content": [{"type": "text", "text": <json-or-string>}]}`.

`emit_rating` is the session-terminating tool. It writes the structured rating into a per-
session result file (a Path provided via the `EMIT_RATING_RESULT_PATH` env var that agent.py
sets per session) so the runner can pick it up after the SDK session ends. The SDK message
stream is *also* monitored by agent.py as a belt-and-braces capture (so a missed env var
doesn't lose the rating).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml
from claude_agent_sdk import tool

CROSSWALK_PATH = Path(__file__).resolve().parent / "crosswalk.yaml"

# Cached read of crosswalk.yaml — file is small (~10KB), loaded once per process.
_crosswalk_cache: dict | None = None

def _crosswalk() -> dict:
    global _crosswalk_cache
    if _crosswalk_cache is None:
        _crosswalk_cache = yaml.safe_load(CROSSWALK_PATH.read_text())
    return _crosswalk_cache


def _ok(payload: Any) -> dict[str, Any]:
    """Wrap a JSON-serialisable payload as the MCP-conformant tool result."""
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
    return {"content": [{"type": "text", "text": text}]}


# ---------------------------------------------------------------------------
# 1) compute_distress_coverage — area % from a polygon (shoelace).

@tool(
    "compute_distress_coverage",
    "Given a polygon (list of [x_pct, y_pct] vertices in 0-100 image-percent coordinates) "
    "describing the region affected by a single distress, compute the polygon area as a "
    "percentage of the total image area. Use this to put numbers on PSCI band thresholds "
    "(10%, 30%, 50%) instead of guessing surface coverage.",
    {
        "polygon_pcts": list,
        "distress_label": str,
    },
)
async def compute_distress_coverage(args: dict) -> dict[str, Any]:
    polygon: list = args.get("polygon_pcts") or []
    label: str = args.get("distress_label") or "(unspecified)"
    if not isinstance(polygon, list) or len(polygon) < 3:
        return _ok({"error": "polygon_pcts must be a list of >=3 [x, y] vertices in 0-100 coords", "received_len": len(polygon) if isinstance(polygon, list) else None})
    try:
        verts = [(float(p[0]), float(p[1])) for p in polygon]
    except (TypeError, IndexError, ValueError) as e:
        return _ok({"error": f"polygon_pcts vertex parse failed: {e}"})
    # Shoelace formula. Area is in (image-percent)^2; divide by 100 to get % of image area.
    n = len(verts)
    s = 0.0
    for i in range(n):
        x1, y1 = verts[i]
        x2, y2 = verts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    area_pct_sq = abs(s) / 2.0
    area_pct_of_image = area_pct_sq / 100.0
    return _ok({
        "distress_label": label,
        "n_vertices": n,
        "area_pct_of_image": round(area_pct_of_image, 2),
        "interpretation": _coverage_interpretation(area_pct_of_image),
    })


def _coverage_interpretation(pct: float) -> str:
    if pct < 5:
        return "very low coverage; isolated occurrences"
    if pct < 10:
        return "low coverage (under PSCI 7-8 threshold of ~10%)"
    if pct < 30:
        return "moderate coverage (between PSCI 5-7 and PSCI 3-4 thresholds)"
    if pct < 50:
        return "high coverage (approaching PSCI 1-3 territory)"
    return "very high coverage (PSCI 1-2 / failed pavement signal)"


# ---------------------------------------------------------------------------
# 2) psci_rubric_lookup — return the manual's text for one PSCI rating.

# Parsed once at import time from the Model 5 rubric (the same text the single-call prompt
# ships). Note: that rubric labels its lines "Rating N", not "Level N", so this parser finds
# no entries and psci_rubric_lookup returns "(no rubric line found)" plus the band signature.
# This is the behaviour the harness ran with.
def _parse_rubric() -> dict[int, str]:
    from . import xu
    out: dict[int, str] = {}
    for line in xu.model5_prompt()["rubric"].splitlines():
        line = line.strip()
        if not line:
            continue
        # Lines look like: "Level 8: <description>"
        if line.startswith("Level "):
            try:
                head, body = line.split(":", 1)
                rating = int(head.replace("Level", "").strip())
                out[rating] = body.strip()
            except ValueError:
                continue
    return out

_RUBRIC = _parse_rubric()
_BAND_SIGNATURES = _crosswalk().get("psci_band_signatures", {}) if CROSSWALK_PATH.exists() else {}


@tool(
    "psci_rubric_lookup",
    "Return the Feighan & Mulry (2013) PSCI rubric definition for one rating. Use this to "
    "verify, before emitting a draft rating, that your evidence (distress types + severities "
    "+ coverage) matches what the manual says a road of rating N looks like. If your evidence "
    "doesn't match the rubric for N, reconsider.",
    {
        "rating_int": int,
    },
)
async def psci_rubric_lookup(args: dict) -> dict[str, Any]:
    rating = args.get("rating_int")
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        return _ok({"error": "rating_int must be an integer 1-10", "received": rating})
    if rating < 1 or rating > 10:
        return _ok({"error": "rating_int must be in [1, 10]", "received": rating})
    return _ok({
        "rating": rating,
        "rubric_text": _RUBRIC.get(rating, "(no rubric line found)"),
        "band_signature": _BAND_SIGNATURES.get(rating, "(no band signature)"),
    })


# ---------------------------------------------------------------------------
# 3) distress_taxonomy_crosswalk — translate observed terms to PSCI vocabulary.

@tool(
    "distress_taxonomy_crosswalk",
    "Given a free-text distress term (eg 'chicken-wire crack', 'spalling', 'fatting up'), "
    "return the canonical PSCI vocabulary entry from the Feighan & Mulry manual plus LTPP "
    "DIM and ASTM D6433 aliases, severity cues, and distinguish_from notes. Use this when "
    "your distress detector reports a term that isn't directly in PSCI vocabulary.",
    {
        "observed_term": str,
    },
)
async def distress_taxonomy_crosswalk(args: dict) -> dict[str, Any]:
    term = (args.get("observed_term") or "").strip().lower()
    if not term:
        return _ok({"error": "observed_term is required and must be non-empty"})
    cw = _crosswalk()
    matches: list[dict] = []
    cats = cw.get("distress_categories", {}) or {}
    for category_name, entries in cats.items():
        for entry in entries or []:
            psci_term = (entry.get("psci_term") or "").lower()
            aliases = [a.lower() for a in (entry.get("aliases") or [])]
            ltpp_terms = [t.lower() for t in (entry.get("ltpp") or [])]
            astm_terms = [t.lower() for t in (entry.get("astm_d6433") or [])]
            haystack = [psci_term] + aliases + ltpp_terms + astm_terms
            if any(term in h or h in term for h in haystack):
                matches.append({
                    "category": category_name,
                    "psci_term": entry.get("psci_term"),
                    "aliases": entry.get("aliases", []),
                    "ltpp": entry.get("ltpp", []),
                    "astm_d6433": entry.get("astm_d6433", []),
                    "definition": entry.get("definition"),
                    "severity_cues": entry.get("severity_cues"),
                    "distinguish_from": entry.get("distinguish_from"),
                })
    if not matches:
        return _ok({"observed_term": term, "matches": [], "note": "no PSCI / LTPP / ASTM crosswalk entry contained this term as a substring; consider using one of the canonical distress terms (Ravelling, Bleeding, Cracking, Rutting, Pothole, Edge Breakup, Patching, Deformation)."})
    return _ok({"observed_term": term, "matches": matches})


# ---------------------------------------------------------------------------
# 4) list_band_signatures — PSCI band → typical distress signature.

@tool(
    "list_band_signatures",
    "Return the PSCI band → typical distress signature dictionary from the Feighan & Mulry "
    "manual (Section 3, pp.25-43). Use this "
    "as priors when sanity-checking a draft rating: does the band signature for your proposed "
    "rating match the distresses you observed? If not, reconsider.",
    {},
)
async def list_band_signatures(args: dict) -> dict[str, Any]:
    return _ok({"psci_band_signatures": _BAND_SIGNATURES})


# ---------------------------------------------------------------------------
# 5) read_manual_section — return text from a manual section.

# Curated, in-memory section catalog derived from the four PSCI-relevant manuals. Each entry
# is short (~200-400 words) and quotes the manual's procedural language. The agent uses this
# when it wants authoritative text on a specific topic without paying the cost of paging
# through the full PDF via Read+Bash.
_MANUAL_SECTIONS: dict[str, dict[str, str]] = {
    "feighan-mulry-2013": {
        "deterioration-modes": (
            "The manual identifies three deterioration modes the rater should reason about "
            "when justifying a PSCI score:\n"
            "  - environmental: weathering / aging — binder hardening, ravelling, block cracking;\n"
            "  - structural: repeated traffic loading — alligator cracking, rutting >50 mm, edge breakup;\n"
            "  - unsuitable_materials: subgrade consolidation, subsidence, surface distortion.\n"
            "Tying observed distress evidence to a deterioration mode strengthens the rationale."
        ),
        "psci-7-8-band": (
            "PSCI 7: early-stage cracking and/or low-severity surface defects. "
            "PSCI 8: isolated minor cracks or surface defects; no deformation. "
            "These bands should NOT show rutting, alligator cracking, edge breakup, or coverage above ~10% of any single distress."
        ),
        "psci-5-6-band": (
            "PSCI 5-6: moderate cracking, possible early ravelling/bleeding. PSCI 5 may show first signs "
            "of structural distress (early alligator, mild rutting). Coverage thresholds: each major distress "
            "below ~30%."
        ),
        "psci-3-4-band": (
            "PSCI 3-4: structural distress emerging or advanced. PSCI 4 shows alligator and/or moderate-severity "
            "rutting with edge breakup. PSCI 3 shows high-severity alligator, deeper rutting, edge breakup, and "
            "incipient potholes. Coverage of structural distress typically 30-50%."
        ),
        "psci-1-2-band": (
            "PSCI 1-2: near-failure. Extensive distress combinations, road disintegration beginning, "
            "loss of cross-section. Surface coverage of structural distress typically >50%. "
            "PSCI 1 = failed pavement, not safely trafficable without major rehabilitation."
        ),
    },
    "ltpp-dim": {
        "alligator-cracking-severity": (
            "LTPP DIM (FHWA-HRT-13-092) defines alligator cracking severity:\n"
            "  - Low: an area of cracks with no or only a few connecting cracks; cracks are not spalled or sealed; "
            "pumping is not evident.\n"
            "  - Medium: an area of interconnected cracks forming a complete pattern; cracks may be slightly "
            "spalled; cracks may be sealed; pumping is not evident.\n"
            "  - High: an area of moderately or severely spalled interconnected cracks forming a complete pattern; "
            "pieces may move when subjected to traffic; cracks may be sealed; pumping may be evident."
        ),
        "rutting-severity": (
            "LTPP DIM rutting severity by mean depth (across the wheel path):\n"
            "  - Low: 6-12 mm (1/4 - 1/2 in.).\n"
            "  - Medium: 13-25 mm (1/2 - 1 in.).\n"
            "  - High: > 25 mm (> 1 in.)."
        ),
    },
    "wsdot-asphalt": {
        "field-rating-procedure": (
            "WSDOT field rating procedure: walk a 100-ft segment; for each distress type encountered, "
            "estimate (1) extent (% of pavement area), (2) severity (low / medium / high per LTPP DIM "
            "definitions). For PSCI, the rater integrates across all observed distresses to a single 1-10 score."
        ),
    },
}


@tool(
    "read_manual_section",
    "Return curated text from one of the PSCI-relevant manuals. Use when you need the "
    "manual's authoritative wording on a specific topic (eg 'alligator-cracking-severity', "
    "'psci-7-8-band'). Available manuals: feighan-mulry-2013, ltpp-dim, wsdot-asphalt.",
    {
        "manual_id": str,
        "section_name": str,
    },
)
async def read_manual_section(args: dict) -> dict[str, Any]:
    manual_id = (args.get("manual_id") or "").strip()
    section = (args.get("section_name") or "").strip()
    if manual_id not in _MANUAL_SECTIONS:
        return _ok({"error": f"unknown manual_id '{manual_id}'", "available": list(_MANUAL_SECTIONS.keys())})
    sections = _MANUAL_SECTIONS[manual_id]
    if section not in sections:
        return _ok({
            "error": f"unknown section '{section}' in manual '{manual_id}'",
            "available_sections": list(sections.keys()),
        })
    return _ok({"manual_id": manual_id, "section_name": section, "text": sections[section]})


# ---------------------------------------------------------------------------
# 6) emit_rating — session-terminating commit.

# Module-level state: agent.py sets EMIT_RATING_RESULT_PATH per session before invoking
# query(). emit_rating writes the structured rating to that file. If the env var is unset
# (eg standalone testing), the result is also retained in memory at _LAST_EMIT.

_LAST_EMIT: dict | None = None


@tool(
    "emit_rating",
    "Commit the final PSCI rating and end the session. Call this exactly ONCE per image, "
    "after you have decided on a rating supported by your evidence (distresses observed, "
    "their severities, the manual's band signature). The session terminates after this call; "
    "do not call any other tool afterwards.",
    {
        "rating_int_1_10": int,
        "rationale_text": str,
        "distresses_observed": list,
        "severities": dict,
    },
)
async def emit_rating(args: dict) -> dict[str, Any]:
    global _LAST_EMIT
    rating = args.get("rating_int_1_10")
    rationale = args.get("rationale_text") or ""
    distresses = args.get("distresses_observed") or []
    severities = args.get("severities") or {}

    payload = {
        "rating_int_1_10": rating,
        "rationale_text": rationale,
        "distresses_observed": distresses,
        "severities": severities,
    }
    _LAST_EMIT = payload

    out_path = os.environ.get("EMIT_RATING_RESULT_PATH")
    if out_path:
        try:
            Path(out_path).write_text(json.dumps(payload, indent=2))
        except OSError as e:
            return _ok({"status": "rating_received_but_write_failed", "error": str(e), "rating": rating})

    return _ok({"status": "rating_recorded", "rating": rating, "note": "session may end now"})


def get_last_emit() -> dict | None:
    """For standalone testing / belt-and-braces capture from agent.py."""
    return _LAST_EMIT


def reset_last_emit() -> None:
    global _LAST_EMIT
    _LAST_EMIT = None


# ---------------------------------------------------------------------------
# Tool registry — agent.py imports ALL_TOOLS and passes to create_sdk_mcp_server.

ALL_TOOLS = [
    compute_distress_coverage,
    psci_rubric_lookup,
    distress_taxonomy_crosswalk,
    list_band_signatures,
    read_manual_section,
    emit_rating,
]
