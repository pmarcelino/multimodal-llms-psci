# Data

This repository does not contain any images, labels or prompt text from Xu et al.

`python -m psci_repro fetch-data` downloads the following files from Xu et al.'s repository
<https://github.com/xushuoshuoxss/zero-shot-psci-llm-prompts> at commit
`48cb13d2ffef8a363d7e64596cf72f9e86186d21` into `data/xu/`. This folder is ignored by git.

- `Dataset_1/*.jpg|png`: the 42 Xu Dataset 1 images.
- `Evaluation (Dataset 1).md`: the ground-truth PSCI levels, parsed by `psci_repro/xu.py`.
- `Model_5.ipynb`: the Model 5 prompt, extracted by `psci_repro/xu.py`.

Every file is checked against `xu_manifest.csv` (size and SHA-256). The labels and the
prompt extracted from them are also checked against the hashes of the labels and prompt
used in the runs (`LABELS_SHA256` and `PROMPT_SHA256` in `psci_repro/xu.py`).

At the time of writing, the upstream repository has no license. If you use these files for
anything beyond reproducing this study, check with the upstream authors and cite:

> Xu, S., Zhao, K., Loney, J., Li, Z., & Visentin, A. (2025). Image-based large language model
> approach to road pavement monitoring. *Computer-Aided Civil and Infrastructure Engineering*,
> 40(26), 4448–4464. https://doi.org/10.1111/mice.70075

The contamination probe also used eight control images (four pavement photographs and four
non-pavement images). These images are not distributed. Their probe grades are in
`results/contamination_probe.jsonl`, but the model's responses to them are not.
