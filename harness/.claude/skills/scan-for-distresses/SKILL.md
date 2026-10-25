---
name: scan-for-distresses
description: Systematic procedure for inspecting a pavement image for the PSCI distress catalog (cracking varieties, rutting, ravelling, edge breakup, potholes, patching, deformation). Use when starting the rating workflow on a fresh image, before delegating to severity-rater or coverage-estimator.
allowed-tools:
  - Read
  - mcp__pavement__distress_taxonomy_crosswalk
---

## Procedure (derived from Feighan & Mulry 2013 §3 + WSDOT field rating procedure)

Walk the image as if walking a 100-ft pavement segment. For each pass, look for **one** distress category at a time — single-category passes catch more than holistic gestalt scans.

**Pass 1 — surface defects (top of pavement, cosmetic-to-structural boundary):**
- *Ravelling* — progressive loss of binder and aggregate; surface looks "rough" or grey-textured. Distinguish from edge breakup (which has cracking + layer loss).
- *Bleeding* (aliases: fatting up) — film of excess bituminous material; shiny / sticky appearance, often in wheel paths in hot weather.

**Pass 2 — cracking (most diagnostic for PSCI band):**
- *Longitudinal / transverse* (single straight cracks parallel / perpendicular to centerline) — environmental.
- *Alligator / fatigue* (interconnected polygons in wheel paths) — structural; strong PSCI 4-3 signal at medium severity, PSCI 1-2 at high severity.
- *Block* (interconnected rectangles, full lane) — environmental; mostly hits PSCI 5-7.

**Pass 3 — structural deformation:**
- *Rutting* (longitudinal depressions in wheel paths, ≥6mm = LTPP "low" threshold) — structural.
- *Edge breakup* (cracking + layer loss at the pavement edge) — structural.

**Pass 4 — surface failure:**
- *Potholes* (holes in the pavement surface, typically ≥150mm diameter) — advanced structural failure.
- *Patching* (previously-repaired potholes / utility cuts) — historical context, not a fresh distress.

**Pass 5 — geometric / drainage clues:**
- *Surface distortion / depressions* (low spots holding water, sub-grade subsidence) — unsuitable-materials deterioration mode.

## Output of this skill

After your scan, produce a JSON-shaped distress inventory:

```json
[
  {"distress": "alligator_cracking", "region": "right wheel path, mid-frame", "rough_extent": "moderate"},
  {"distress": "edge_breakup", "region": "right edge, full length", "rough_extent": "small"}
]
```

Pass this inventory to `severity-rater` (per distress) and `coverage-estimator` (per distress) for the next stage.

## When to invoke `distress_taxonomy_crosswalk`

If your detector or your own observation produces a term that isn't in the PSCI vocabulary above (e.g. "chicken-wire crack", "spalling", "fatting up"), call `mcp__pavement__distress_taxonomy_crosswalk(observed_term)` to translate it before passing to the next stage.
