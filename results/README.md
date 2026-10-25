# Cached outputs

These are the model outputs behind the numbers in the paper. `python -m psci_repro reproduce-cache`
recomputes the numbers from these files. Ground-truth labels are not stored here; they are
read from Xu et al.'s evaluation file, which `fetch-data` downloads.

`cost_usd` is an estimate computed from token counts at per-token prices hard-coded in
`psci_repro/api.py` and `psci_repro/openai_api.py`. For the agent's SDK session it is the
cost reported by the Claude Agent SDK. It is not a billed amount. `latency_s` is the latency
reported for the API call(s) in that row.

## `gpt4o_baseline.jsonl` (420 rows)

Xu Model 5 prompt on the bare `gpt-4o` alias, temperature 0, `max_tokens` 300, with 10
replicates per image.

| Field | Meaning |
| --- | --- |
| `image_id` | Xu Dataset 1 image id, 1–42 |
| `replicate` | 0–9 |
| `rating` | PSCI rating parsed from the response |
| `parse_failed` | true if no rating could be parsed (no such rows) |
| `model_id` | requested model |
| `model_version` | model version reported by the API (`gpt-4o-2024-08-06`) |
| `input_tokens`, `output_tokens`, `latency_s`, `cost_usd` | per call |

## `opus_baseline.jsonl` (42 rows)

The same prompt on `claude-opus-4-7`, `max_tokens` 300, with one replicate per image. The
temperature parameter is not sent because this model rejects it. The fields are the same as
above.

## `opus_agent.jsonl` (42 rows)

One agent run per image (see `psci_repro/agent.py`). Each run has a draft call and an SDK
session. The draft call is a separate request with the same prompt and settings as the Opus
baseline. Runs that ended with an API or SDK error before producing a rating were run again;
this file holds the 42 completed runs.

| Field | Meaning |
| --- | --- |
| `image_id`, `replicate`, `parse_failed`, `model_id`, `model_version` | as above |
| `draft_rating` | rating from the draft call |
| `agent_rating` | rating committed by the SDK session through `emit_rating`; this is the agent's final rating |
| `override_fired` | true if `agent_rating` differs from `draft_rating` |
| `distresses_observed`, `severities`, `rationale_text` | arguments the session passed to `emit_rating` |
| `tool_calls_log` | tool calls made by the lead session (long inputs truncated, image paths relative to the repository) |
| `input_tokens`, `output_tokens`, `latency_s`, `cost_usd` | summed over the draft call and the SDK session |

## `contamination_probe.jsonl` (200 rows)

`claude-opus-4-7` was asked four recall questions per image, with `max_tokens` 400. The images
were the 42 Xu Dataset 1 images plus 8 control images. Each response was graded 0–3 by
`gpt-5.5-2026-04-23`, which saw only the question and the response. Table I of the paper
reports the maximum level per image.

| Field | Meaning |
| --- | --- |
| `image_id` | 1–42 for Xu images; `pavement_a`–`pavement_d` and `nonpavement_a`–`nonpavement_d` for controls |
| `image_set` | `xu_dataset_1`, `control_pavement` or `control_non_pavement` |
| `filename` | image file name |
| `probe_question` | `q1` recognition, `q2` source, `q3` label, `q4` free recall (texts in `psci_repro/probe.py`) |
| `replicate` | 0 |
| `response_text` | the model's answer; `null` for control images, which are not distributed |
| `contamination_level` | judge grade, 0–3 |
| `judge_rationale` | the judge's one-sentence justification |
| `model_id`, `judge_model` | probed model and judge model |
| `input_tokens`, `output_tokens` | for the probe call |
