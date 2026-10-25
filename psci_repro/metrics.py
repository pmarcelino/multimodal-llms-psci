"""Metrics, the paper-number check on results/*.jsonl, and summaries of rerun directories."""

from __future__ import annotations

import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median, stdev

from . import xu

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "results"

BOOTSTRAP_SEED = 42
# Resample counts that produced the printed H1 and H2 intervals.
H1_RESAMPLES = 5000
H2_RESAMPLES = 1000


def load_jsonl(path: Path) -> list[dict]:
    """Load rows, dropping failed rows and keeping the last row per (image_id, replicate)."""
    rows: dict[tuple, dict] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if not r.get("parse_failed"):
                rows[(r["image_id"], r.get("probe_question"), r.get("replicate"))] = r
    return list(rows.values())


def _rating(row: dict) -> int:
    return int(row["agent_rating"] if "agent_rating" in row else row["rating"])


def per_image_errors(rows: list[dict], labels: dict[int, int], power: int = 1) -> dict[int, float]:
    by_image: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        by_image[r["image_id"]].append(abs(_rating(r) - labels[r["image_id"]]) ** power)
    return {i: mean(v) for i, v in by_image.items()}


def pearson(xs: list[float], ys: list[float]) -> float:
    mx, my = mean(xs), mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / math.sqrt(sxx * syy) if sxx and syy else float("nan")


def quadratic_weighted_kappa(y_true: list[int], y_pred: list[int], levels=range(1, 11)) -> float:
    levels = list(levels)
    k = len(levels)
    idx = {v: i for i, v in enumerate(levels)}
    obs = [[0] * k for _ in range(k)]
    for t, p in zip(y_true, y_pred):
        obs[idx[int(p)]][idx[int(t)]] += 1
    n = len(y_true)
    row = [sum(r) / n for r in obs]
    col = [sum(obs[i][j] for i in range(k)) / n for j in range(k)]
    w = [[((i - j) / (k - 1)) ** 2 for j in range(k)] for i in range(k)]
    num = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k))
    den = sum(w[i][j] * row[i] * col[j] * n for i in range(k) for j in range(k))
    return 1.0 - num / den if den else float("nan")


def config_metrics(rows: list[dict], labels: dict[int, int]) -> dict:
    """MAE/MSE: mean over images of the per-image mean error (equal to the mean of per-run
    values when every replicate parsed). r: per-run Pearson averaged over replicates.
    Weighted kappa: per-image median rating (truncated to int) vs label."""
    by_rep: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        by_rep[r["replicate"]].append(r)
    r_val = mean(
        pearson([_rating(x) for x in rep], [labels[x["image_id"]] for x in rep]) for rep in by_rep.values()
    )
    by_image: dict[int, list[int]] = defaultdict(list)
    for r in rows:
        by_image[r["image_id"]].append(_rating(r))
    ids = sorted(by_image)
    run_maes = [mean(abs(_rating(x) - labels[x["image_id"]]) for x in rep) for rep in by_rep.values()]
    return {
        "n": len(ids),
        "mae": mean(per_image_errors(rows, labels).values()),
        "mse": mean(per_image_errors(rows, labels, power=2).values()),
        "r": r_val,
        "kappa": quadratic_weighted_kappa([labels[i] for i in ids], [int(median(by_image[i])) for i in ids]),
        "cost": sum(r.get("cost_usd") or 0.0 for r in rows),
        "run_mae_sd": stdev(run_maes) if len(run_maes) > 1 else None,
    }


def bootstrap_delta(pim_a: dict, pim_b: dict, n_resamples: int, seed: int = BOOTSTRAP_SEED) -> tuple[float, float, float]:
    """Image-level paired bootstrap of MAE(a) - MAE(b); 95% percentile interval."""
    common = sorted(set(pim_a) & set(pim_b))
    rng = random.Random(seed)
    deltas = []
    for _ in range(n_resamples):
        sample = [rng.choice(common) for _ in range(len(common))]
        deltas.append(mean(pim_a[i] for i in sample) - mean(pim_b[i] for i in sample))
    deltas.sort()
    point = mean(pim_a[i] for i in common) - mean(pim_b[i] for i in common)
    return point, deltas[int(round(0.025 * n_resamples))], deltas[int(round(0.975 * n_resamples)) - 1]


class _Checker:
    def __init__(self) -> None:
        self.failures = 0

    def __call__(self, label: str, computed, expected: str, fmt: str = "{:.3f}") -> None:
        shown = fmt.format(computed)
        ok = shown == expected
        self.failures += not ok
        print(f"  {'OK ' if ok else 'XX '} {label:30s} computed={shown:>9s}  paper={expected:>9s}")


def reproduce_cache(results_dir: Path = RESULTS_DIR) -> int:
    labels = xu.labels()
    check = _Checker()
    gpt4o = load_jsonl(results_dir / "gpt4o_baseline.jsonl")
    opus = load_jsonl(results_dir / "opus_baseline.jsonl")
    agent = load_jsonl(results_dir / "opus_agent.jsonl")
    probe = load_jsonl(results_dir / "contamination_probe.jsonl")

    print("Table I: per-image maximum contamination level")
    per_image: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for r in probe:
        per_image[r["image_set"]][r["image_id"]] = max(per_image[r["image_set"]][r["image_id"]], r["contamination_level"])
    expected_probe = {
        "xu_dataset_1": ("42", ["18", "19", "5", "0"]),
        "control_pavement": ("4", ["4", "0", "0", "0"]),
        "control_non_pavement": ("4", ["4", "0", "0", "0"]),
    }
    for image_set, (n, dist) in expected_probe.items():
        counts = Counter(per_image[image_set].values())
        check(f"{image_set} n", len(per_image[image_set]), n, "{}")
        for level in range(4):
            check(f"{image_set} L{level}", counts.get(level, 0), dist[level], "{}")

    print("\nTable II / Table IV: per-configuration metrics")
    expected = {
        "GPT-4o baseline": (gpt4o, "1.321", "2.755", "0.866", "0.787", "$2.93"),
        "Opus baseline": (opus, "1.024", "1.929", "0.877", "0.854", "$2.48"),
        "Agent": (agent, "1.071", "2.119", "0.855", "0.838", "$23.08"),
    }
    pims = {}
    for name, (rows, mae, mse, r, kappa, cost) in expected.items():
        m = config_metrics(rows, labels)
        pims[name] = per_image_errors(rows, labels)
        print(f" {name} (n={m['n']}, rows={len(rows)})")
        check("MAE", m["mae"], mae)
        check("MSE", m["mse"], mse)
        check("Pearson r", m["r"], r)
        check("weighted kappa", m["kappa"], kappa)
        check("cost", m["cost"], cost, "${:.2f}")
        if name == "GPT-4o baseline":
            check("SD of the 10 per-run MAEs", m["run_mae_sd"], "0.036")

    print("\nTable III: agent overrides (|agent - draft| >= 2)")
    expected_overrides = {9: (6, 8, 5, 2, "N"), 14: (7, 5, 7, 2, "N"), 31: (7, 5, 4, 2, "Y"), 33: (8, 5, 6, 3, "Y")}
    found = {}
    for r in agent:
        draft, final, gt = r["draft_rating"], r["agent_rating"], labels[r["image_id"]]
        if abs(final - draft) >= 2:
            found[r["image_id"]] = (draft, final, gt, abs(final - draft), "Y" if abs(final - gt) < abs(draft - gt) else "N")
    print(f"  {'image':>5} {'draft':>5} {'agent':>5} {'label':>5} {'|d|':>3} closer?")
    for image_id, (draft, final, gt, d, closer) in sorted(found.items()):
        print(f"  {image_id:>5} {draft:>5} {final:>5} {gt:>5} {d:>3} {closer:>7}")
    check("override rows match", found == expected_overrides, "True", "{}")

    print(f"\nH1: MAE(GPT-4o) - MAE(Opus), image-level paired bootstrap, {H1_RESAMPLES} resamples, seed {BOOTSTRAP_SEED}")
    point, lo, hi = bootstrap_delta(pims["GPT-4o baseline"], pims["Opus baseline"], H1_RESAMPLES)
    check("delta", point, "0.298")
    check("95% CI lower", lo, "0.014")
    check("95% CI upper", hi, "0.605")

    print(f"\nH2: MAE(Opus) - MAE(Agent), image-level paired bootstrap, {H2_RESAMPLES} resamples, seed {BOOTSTRAP_SEED}")
    point, lo, hi = bootstrap_delta(pims["Opus baseline"], pims["Agent"], H2_RESAMPLES)
    check("delta", point, "-0.048")
    check("95% CI lower", lo, "-0.238")
    check("95% CI upper", hi, "0.119")

    print("\nAll values match the paper." if not check.failures else f"\n{check.failures} value(s) differ from the paper.")
    return 1 if check.failures else 0


def summarize(path: Path) -> int:
    """Print metrics per configuration. Returns nonzero if no result file exists or if any
    result file has no completed rows."""
    labels = xu.labels()
    found = False
    empty = False
    for filename, label in (("gpt4o_baseline.jsonl", "GPT-4o baseline"), ("opus_baseline.jsonl", "Opus baseline"),
                            ("opus_agent.jsonl", "Agent")):
        if (path / filename).exists():
            found = True
            rows = load_jsonl(path / filename)
            if not rows:
                empty = True
                print(f"{label:16s} no completed rows")
                continue
            m = config_metrics(rows, labels)
            print(f"{label:16s} images={m['n']:>2} rows={len(rows):>3} MAE={m['mae']:.3f} MSE={m['mse']:.3f} "
                  f"r={m['r']:.3f} kappa={m['kappa']:.3f} cost=${m['cost']:.2f}")
    if not found:
        print(f"no result files in {path}")
    return 0 if found and not empty else 1
