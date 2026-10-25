---
name: sanity-check-against-band-exemplars
description: Final gate before emit_rating — cross-check that the proposed PSCI integer is consistent with the manual's band signature AND the dominant deterioration mode visible in the image. Use after apply-psci-band-signature, immediately before committing the rating.
allowed-tools:
  - Read
  - mcp__pavement__list_band_signatures
  - mcp__pavement__read_manual_section
---

## Procedure

You have a draft rating + a list of distresses + severities + coverages. Run three sanity checks before calling `emit_rating`. If any check fails, walk the rating one band up or down and re-run.

### Check 1 — band signature consistency

Call `mcp__pavement__list_band_signatures()`. Read the signature line for your proposed rating.

- Does the signature mention distresses you observed? ✅
- Does the signature mention distresses you did NOT observe at the severity it implies? ❌ → reconsider.
- Are the severities in your evidence consistent with the signature's adjective ("isolated minor" vs "moderate" vs "advanced")? If your evidence is lower than the signature implies, walk up; if higher, walk down.

### Check 2 — deterioration mode consistency

The manual identifies three deterioration modes:
- **Environmental** — weathering, ageing, binder hardening (ravelling, block cracking, bleeding)
- **Structural** — repeated traffic loading (alligator cracking, rutting >50mm, edge breakup, potholes)
- **Unsuitable materials** — subgrade consolidation, subsidence (surface distortion, depressions)

Your rationale should name the dominant mode. If you proposed PSCI 4 but described only environmental distress, that's inconsistent — environmental-only roads usually land at PSCI 5-7. Conversely, a structural-distress-only road rarely lands above PSCI 6.

### Check 3 — the band-checker sub-agent's verdict

If you have not yet delegated to `band-checker`, do so now via the `Agent` tool. The sub-agent will return either "consistent" or "inconsistent + reason". If "inconsistent", revise the rating per the reason and re-run all three checks.

### Common failure modes to catch

- **Over-rating environmentally-distressed roads.** A road with extensive ravelling but no structural distress is PSCI 5-6, not 7-8 — the rubric does penalise heavy environmental distress.
- **Under-rating roads with one bad patch.** A pavement with one localised pothole and otherwise PSCI 7-quality surface is still PSCI 7 (not 4) — coverage matters as much as presence.
- **Misclassifying alligator cracking as longitudinal.** Alligator cracks form in interconnected polygons; longitudinal cracks are single straight lines. The PSCI implications differ by 2-3 bands.
- **Treating patching as fresh distress.** Patches are repaired distress; they signal the *history* of a road but are not themselves a current distress to count against the rating.

### Output of this skill

Either:
- **PASS**: proceed to `emit_rating` with the draft rating + a 2-4 sentence rationale that explicitly cites the band signature and the dominant deterioration mode.
- **FAIL**: walk the rating up or down by one and re-enter `apply-psci-band-signature`. Document why in your transcript so the audit trail shows the deliberation.

It is acceptable to keep the same rating after this skill if all three checks pass on the first try; the act of running the checks is the point, even when the answer doesn't change.
