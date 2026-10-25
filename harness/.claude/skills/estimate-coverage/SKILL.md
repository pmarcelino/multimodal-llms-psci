---
name: estimate-coverage
description: Estimate the percentage of pavement surface area affected by a single distress, mapped to PSCI band thresholds (10%, 30%, 50%). Use after classifying severity, before applying the band signature. Coverage drives band placement when severity is constant.
allowed-tools:
  - Read
  - mcp__pavement__compute_distress_coverage
---

## Procedure (derived from PSCI rubric percentages + LTPP visual area-estimation guidance)

### Why coverage matters

Severity tells you how bad each instance of a distress is; **coverage** tells you how much of the pavement is affected. The PSCI rubric uses three coverage thresholds across the bands:

- **~10%** — boundary between PSCI 7-8 (isolated) and PSCI 5-6 (multiple distress types).
- **~30%** — boundary between PSCI 5-6 (moderate) and PSCI 3-4 (advanced structural).
- **~50%** — boundary between PSCI 3-4 (advanced) and PSCI 1-2 (near-failure).

Two roads with identical distress catalogs but different coverage land in different bands. Get the coverage right.

### Two estimation methods (pick whichever fits the evidence)

**Method 1 — visual percentage estimate (default).**

Mentally divide the visible pavement into 10% bands (10 strips, 5 horizontal × 2 vertical). For each distress, count the bands fully or substantially affected. Round to the nearest 10%.

This is fast, conservative-biased, and accurate enough for PSCI band placement. Use it for "obvious" cases.

**Method 2 — polygon math via `compute_distress_coverage` (use when the call is close to a band threshold).**

When your visual estimate is within ~5% of a threshold (eg 8% or 12% for the PSCI 7-8 ↔ 5-6 boundary), instead use the MCP tool:

1. Mentally trace a polygon around the affected region. The polygon is a list of vertices in `[x_pct, y_pct]` image-percent coords (the image is the unit; (0,0) is top-left, (100,100) is bottom-right).
2. Call `mcp__pavement__compute_distress_coverage(polygon_pcts=[[x1,y1], [x2,y2], ...], distress_label="alligator_cracking")`.
3. The tool returns `area_pct_of_image` plus an interpretation flag aligning to the band thresholds.

Don't over-use Method 2 — it's for boundary calls only. Visual estimation is fine for clearly-low (<5%) or clearly-high (>50%) coverage.

### Important caveats

- **The image shows a slice, not the whole road.** The PSCI rubric's coverage thresholds are over the full pavement segment; you are inferring from a single image. Bias your estimate slightly conservative (down) when the image looks like a representative sample of a longer segment.
- **Patching is "historical context", not coverage.** Patched areas are repaired distress; don't double-count them as current distress, but do note them in the rationale (a heavily-patched pavement is usually PSCI 4-5, regardless of whether the patches themselves are intact).
- **Ground-level vs aerial perspective.** Most Xu Dataset 1 images are oblique ground-level shots from approximately 10m back. Foreground distress is over-represented relative to the actual pavement area; correct for this when the shot is heavily oblique.

## Output of this skill

For each distress, return `{distress, severity, coverage_pct}` where coverage_pct is an integer 0-100. Pass this triple to `band-checker` for the PSCI placement.
