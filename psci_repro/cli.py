"""Command-line interface: python -m psci_repro <command>."""

from __future__ import annotations

import argparse
from pathlib import Path


def _ids(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def _configs(raw: str) -> list[str]:
    from .runs import CONFIGS

    out = [x.strip() for x in raw.split(",") if x.strip()]
    bad = sorted(set(out) - set(CONFIGS))
    if bad:
        raise argparse.ArgumentTypeError(f"unknown config(s) {bad}; choose from {sorted(CONFIGS)}")
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m psci_repro")
    sub = p.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch-data", help="Download Xu Dataset 1 (images, labels, Model 5 notebook) at the pinned commit.")
    fetch.add_argument("--force", action="store_true", help="Download again even if verified files exist.")
    sub.add_parser("verify-data", help="Check data/xu/ against data/xu_manifest.csv.")

    cache = sub.add_parser("reproduce-cache", help="Recompute the paper's numbers from results/*.jsonl (no API calls).")
    cache.add_argument("--results-dir", type=Path, default=None)

    run = sub.add_parser("run", help="Re-run the rating configurations with live API calls.")
    run.add_argument("--configs", type=_configs, default=["gpt4o", "opus", "agent"], help="Comma-separated: gpt4o,opus,agent")
    run.add_argument("--image-ids", type=_ids, default=None, help="Comma-separated image ids (default: all 42).")
    run.add_argument("--replicates", type=int, default=None, help="Override replicates per image (default: 10 / 1 / 1).")
    run.add_argument("--output", type=Path, default=None, help="Output directory (default: results/rerun_<UTC time>). Reuse it to resume.")

    probe = sub.add_parser("probe", help="Re-run the contamination probe and judge on Xu Dataset 1 with live API calls.")
    probe.add_argument("--image-ids", type=_ids, default=None)
    probe.add_argument("--output", type=Path, default=None)

    summ = sub.add_parser("summarize", help="Score the rating results in a directory.")
    summ.add_argument("path", type=Path)
    return p


def _load_env() -> None:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "fetch-data":
        from . import xu

        ok = xu.fetch(force=args.force)
        print("Xu Dataset 1 files verified." if ok else "Verification failed.")
        return 0 if ok else 1
    if args.command == "verify-data":
        from . import xu

        ok = xu.verify()
        print("Xu Dataset 1 files verified." if ok else "Run: python -m psci_repro fetch-data")
        return 0 if ok else 1
    if args.command == "reproduce-cache":
        from . import metrics, xu

        xu.require()
        return metrics.reproduce_cache(args.results_dir or metrics.RESULTS_DIR)
    if args.command == "run":
        _load_env()
        from . import metrics, runs

        out = runs.run(args.configs, args.output, args.image_ids, args.replicates)
        print()
        return metrics.summarize(out)
    if args.command == "probe":
        _load_env()
        from . import probe

        probe.run(args.output, args.image_ids)
        return 0
    if args.command == "summarize":
        from . import metrics

        return metrics.summarize(args.path)
    return 2
