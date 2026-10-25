# Multimodal LLMs for Zero-Shot Pavement Condition Rating: Model Upgrades vs. Agents

This repository has the code and the cached model outputs for:

> P. Marcelino and A. Ferreira, "Multimodal LLMs for Zero-Shot Pavement Condition Rating:
> Model Upgrades vs. Agents," *2026 IEEE International Smart Cities Conference (ISC2)*, Porto,
> Portugal, 2026.

The paper was accepted for IEEE ISC2 2026. It is not included in this repository.

The study rates the 42 photographs of Xu et al.'s Dataset 1 on the 1–10 PSCI scale. It uses
three configurations, all with Xu's Model 5 prompt:

| Config | What it is | Code |
| --- | --- | --- |
| `gpt4o` | GPT-4o, one call per image, 10 replicates | `psci_repro/runs.py` |
| `opus` | Claude Opus 4.7, one call per image | `psci_repro/runs.py` |
| `agent` | Opus 4.7 draft, then a Claude Agent SDK session with 4 sub-agents and MCP tools that audits it | `psci_repro/agent.py`, `psci_repro/tools.py`, `harness/.claude/` |

A contamination probe (`psci_repro/probe.py`) checks whether Opus 4.7 recalls the images.

## Check the paper's numbers (no API keys, no cost)

Tested with Python 3.14, the version used in the study.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m psci_repro fetch-data        # downloads Xu Dataset 1 into data/xu/ and checks hashes
python -m psci_repro reproduce-cache   # recomputes the paper's numbers from results/*.jsonl
```

`reproduce-cache` uses only the Python standard library. It prints each value next to the
value in the paper and ends with `All values match the paper.` It covers:

- Table I: contamination levels per image set.
- Table II and the bottom block of Table IV: MAE, MSE, Pearson r, weighted kappa and cost for
  each configuration, plus the standard deviation of the 10 per-run GPT-4o MAEs (Section III-D).
- Table III: the four agent overrides.
- H1 and H2: the MAE differences and their 95% bootstrap intervals. The bootstrap resamples
  images with seed 42: 5,000 resamples for H1 and 1,000 for H2.

## Re-run the experiments (API keys, costs money)

```bash
cp .env.example .env    # then set ANTHROPIC_API_KEY and OPENAI_API_KEY
python -m psci_repro fetch-data

# smoke test on one image
python -m psci_repro run --configs gpt4o,opus,agent --image-ids 31

# full runs
python -m psci_repro run                      # all three configurations, all 42 images
python -m psci_repro run --configs gpt4o,opus  # only the single-call baselines
python -m psci_repro probe                    # contamination probe on the 42 Xu images
python -m psci_repro summarize results/rerun_<timestamp>
```

Results are written to `results/rerun_<UTC time>/` using the same file formats as `results/`.
To resume an interrupted run, pass the same `--output` directory; rows that failed are retried.

Cost estimates from the cached runs (estimated from token counts, not billed amounts):

| Run | Estimated cost |
| --- | --- |
| `gpt4o`: 420 calls | about $3 |
| `opus`: 42 calls | about $2.50 |
| `agent`: 42 sessions, about 1.5 minutes each | about $23 |
| `probe`: 168 calls plus 168 judge calls | about $4 |

Things to know before re-running:

- **The numbers will not match exactly.** API outputs vary from run to run. The bare `gpt-4o`
  alias may now point to a different snapshot than `gpt-4o-2024-08-06`, the one used in the
  study. Models can also be retired. Use `reproduce-cache` to check the paper's numbers.
- **Responses are cached in `.cache/`.** A repeated run with identical settings reuses the cached
  responses. Delete `.cache/` to make fresh calls.
- **The agent can run shell commands.** As in the study, the SDK session can use `Read`, `Bash`,
  `Glob`, `Grep`, `Edit` and `Write`, with edits auto-accepted. Its working directory is
  `harness/`. Run it in a container or VM if that is a concern.
- **Agent SDK version.** The study used `claude-agent-sdk` 0.1.75, which is no longer on PyPI.
  `requirements.txt` pins 0.1.76, the next release.
- **Contamination-probe controls.** The eight control images are not distributed. `probe`
  covers the 42 Xu images only.

## Layout

```
psci_repro/        CLI and code: xu.py (data + prompt), runs.py (configurations), agent.py,
                   tools.py + crosswalk.yaml (agent tools), probe.py, metrics.py
harness/.claude/   project context, sub-agents and skills loaded by the agent session
results/           cached outputs behind the paper's numbers (see results/README.md)
data/              manifest of the Xu Dataset 1 files (see data/README.md)
```

The files in `harness/.claude/` and the tool code in `psci_repro/tools.py` are the ones the agent
used in the study, except that internal project references (project names, file paths, notes on
development iterations) were removed from the text after the study. `psci_repro/agent.py` keeps
only the configuration reported in the paper.

## Data

Xu et al.'s images, labels and prompt are not redistributed. `fetch-data` downloads them from
<https://github.com/xushuoshuoxss/zero-shot-psci-llm-prompts> at a pinned commit and checks
them against SHA-256 hashes. See `data/README.md`.

## License

The code and the files in `results/` are released under the MIT License (`LICENSE`). This
license does not cover Xu et al.'s material, which is downloaded from its source.
