---
name: apply-psci-band-signature
description: Map a distress inventory (with severities and coverages) to a PSCI rating 1-10 using the band signatures from the Feighan & Mulry manual. Use after estimating coverage, before sanity-checking. This is the integrative step where individual evidence becomes one integer.
allowed-tools:
  - Read
  - mcp__pavement__list_band_signatures
  - mcp__pavement__psci_rubric_lookup
  - mcp__pavement__read_manual_section
---

## Procedure (derived from the PSCI band signatures + Feighan & Mulry §3)

### Decision algorithm

Walk **down** from PSCI 10 to find the highest band whose signature your evidence actually matches. The signatures are ordered roughly by severity of allowable distress:

| PSCI | Distress signature (from `mcp__pavement__list_band_signatures`) |
|---|---|
| 10 | new construction; no visible distress |
| 9 | near-new; very minor surface defects only |
| 8 | isolated minor cracks or surface defects; no deformation |
| 7 | early-stage cracking and/or low-severity surface defects |
| 6 | moderate cracking, possible early ravelling/bleeding, no structural distress |
| 5 | multiple distress types at moderate severity; possibly first signs of structural distress |
| 4 | structural distress emerging — alligator and/or rutting at moderate severity, edge breakup |
| 3 | advanced structural distress; high-severity alligator, rutting, edge breakup, potholes |
| 2 | near-failure; extensive distress combinations, road disintegration beginning |
| 1 | failed pavement; not safely trafficable without major rehabilitation |

### Step-by-step

1. **Filter for STRUCTURAL distress first.** If you see *any* alligator cracking, *any* rutting, *any* edge breakup, *any* potholes, the rating cannot be ≥7. Drop to PSCI 6 or below immediately.

2. **For roads with no structural distress** (only ravelling, bleeding, longitudinal/transverse/block cracking):
   - All-low severity, isolated (<10% coverage of any single distress) → PSCI 8 or 9.
   - Multiple distresses at low/medium severity, each <30% coverage → PSCI 6-7.
   - Multiple distresses at medium severity, some >30% coverage → PSCI 5.

3. **For roads with structural distress**:
   - Single structural distress at low severity, low coverage → PSCI 5-6.
   - Single structural at medium severity, OR multiple structural distresses at low severity → PSCI 4.
   - Structural at medium severity AND >30% coverage, OR any high-severity structural distress → PSCI 3.
   - Multiple high-severity structural distresses with >50% coverage → PSCI 2.
   - Road no longer trafficable as-is (continuous potholes, full edge collapse, deep ruts spanning lane width) → PSCI 1.

4. **Cross-check with `psci_rubric_lookup(rating_int=N)`** for your draft N. If the manual's rubric text describes a road that doesn't match your evidence, walk one band up or down and re-check.

### Quick sanity check on the integer call

- Did you propose **PSCI 7-8**? Verify: zero structural distress, all coverage <10%. If any of those fails, drop.
- Did you propose **PSCI 4**? Verify: at least one structural distress at *moderate* severity (not just "present"). If only low-severity structural, propose 5.
- Did you propose **PSCI 1-2**? Verify: the road would be unsafe to drive at speed. PSCI 1-2 is for genuine failure, not just "ugly".

### USE THE FULL SCALE — calibration discipline

The PSCI scale is 1-10. A common failure is clustering ratings around 5-7 for all roads, regardless of actual condition. The fix is **not** to over-correct in the opposite direction. The rule is: **let the evidence place the rating, then trust the band signature.**

- **Pristine pavement** (zero visible cracks, zero rutting, zero edge issues, smooth uniform surface) lands in the 9-10 band per the rubric. Do not rate down to 6-7 for "minor weathering" if you cannot cite a specific distress at a specific severity.
- **Moderate environmental distress** (ravelling, bleeding, longitudinal/transverse cracks, no structural distress) lands in the 6-8 band depending on coverage. PSCI 8 is the right call when distresses exist but are isolated; PSCI 7 when distresses cover ~30% but stay non-structural; PSCI 6 when multiple types are present at moderate coverage.
- **Heavily-distressed pavement** (structural distress at high severity AND >30% coverage, OR multiple high-severity distresses, OR continuous potholes) lands in the 1-3 band per the rubric. Do not pull up to 4-5 because "complete failure feels extreme". The manual's PSCI 2 description ("near-failure; extensive distress combinations, road disintegration beginning") is the calibrated language; if the evidence matches, the rating is 2.

**Do not invent distresses** to justify any particular rating, and **do not invent the absence of distresses** either. The most common failure mode is detection bias in either direction: false positives drop pristine roads into the 5-7 band; false negatives push moderate-distress roads into the 8-9 band. Anchor on what is actually visible, then let the band signature place the integer.

### Output of this skill

A draft `{rating: int, rationale: str, evidence: list}` to pass to `band-checker` for the final sanity-check before `emit_rating`.
