---
name: classify-distress-severity
description: Classify a single distress as low / medium / high severity per LTPP DIM definitions. Use after detecting a distress, before estimating coverage. Severity drives the PSCI band more than presence alone — alligator-low contributes to PSCI 5-6, alligator-high to PSCI 1-2.
allowed-tools:
  - Read
  - mcp__pavement__read_manual_section
---

## Procedure (derived from LTPP DIM 5th rev, FHWA-HRT-13-092)

For each distress in the inventory:

### Alligator (fatigue) cracking

- **Low**: an area of cracks with no or only a few connecting cracks; cracks not spalled or sealed; no pumping evident.
- **Medium**: interconnected cracks forming a complete pattern; cracks may be slightly spalled; may be sealed; no pumping evident.
- **High**: moderately or severely spalled interconnected cracks forming a complete pattern; pieces may move under traffic; may be sealed; pumping may be evident.

(Authoritative wording in `mcp__pavement__read_manual_section(manual_id="ltpp-dim", section_name="alligator-cracking-severity")`.)

### Rutting

- **Low**: 6-12 mm (1/4 - 1/2 in.) mean depth across the wheel path.
- **Medium**: 13-25 mm (1/2 - 1 in.).
- **High**: > 25 mm (> 1 in.).

(Authoritative wording in `mcp__pavement__read_manual_section(manual_id="ltpp-dim", section_name="rutting-severity")`.)

### Longitudinal / transverse cracking

- **Low**: hairline (≤6mm wide) cracks, no associated random cracking, well-sealed or unsealed and dry.
- **Medium**: moderate-width (6-19mm) cracks OR low-severity with a few associated random cracks, partially sealed.
- **High**: wide (>19mm) cracks, broken edges, or extensive associated random cracking.

### Block cracking

- **Low**: blocks defined by cracks of low severity (per long/trans cracking severity).
- **Medium**: blocks defined by cracks of medium severity.
- **High**: blocks defined by cracks of high severity.

### Edge breakup

- **Low**: hairline cracks at edge, no spalling, no loss of material.
- **Medium**: cracks at edge with some spalling and material loss.
- **High**: substantial loss of edge material, deep crescent-shaped voids.

### Potholes

- **Low**: < 25 mm deep.
- **Medium**: 25-50 mm deep.
- **High**: > 50 mm deep.

### Ravelling

- **Low**: aggregate worn but mostly retained; surface has light texture.
- **Medium**: most of new surface lost; older surface exposed beneath in places.
- **High**: extensive loss; underlying course exposed across most of the wheel path.

### Bleeding

- **Low**: localised shiny film, only in hot weather.
- **Medium**: continuous film over wheel paths; tacky to touch.
- **High**: free bituminous material on surface, severe loss of skid resistance.

## Output of this skill

For each distress, return `{distress, severity}` where severity ∈ `{low, medium, high}`. Pass this to `coverage-estimator` and to `band-checker`.

**Be accurate, not conservative.** Rating severities one level lower than warranted collapses the final PSCI rating toward the middle of the 1-10 range. The LTPP definitions are calibrated thresholds, not "minimum to qualify". If a distress matches the LTPP medium description, it is medium; do not down-rate to low because the boundary is fuzzy. Same for high vs medium. The cost of under-rating severity is systematically over-rating PSCI on degraded roads.
