"""Xu et al. (2025) Dataset 1: images, PSCI labels, and the Model 5 prompt.

None of this material is redistributed here. `fetch()` downloads it from the upstream
repository at a pinned commit into data/xu/ and checks every file against
data/xu_manifest.csv (SHA-256). The upstream repository carries no license; see
data/README.md.
"""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
import urllib.parse
import urllib.request
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
XU_DIR = REPO_ROOT / "data" / "xu"
MANIFEST_CSV = REPO_ROOT / "data" / "xu_manifest.csv"

UPSTREAM = "xushuoshuoxss/zero-shot-psci-llm-prompts"
COMMIT = "48cb13d2ffef8a363d7e64596cf72f9e86186d21"

EVAL_MD = "Evaluation (Dataset 1).md"
MODEL5_NB = "Model_5.ipynb"

# SHA-256 of the assembled Model 5 prompt (system text + user text parts) and of the
# {image_id: label} mapping, exactly as used in the runs behind the cached results.
PROMPT_SHA256 = "dd57a84a7920d917c985f982f2138bbc495fd6e37c044f0bfd19e6f9a82cff90"
LABELS_SHA256 = "d86359aab7717ea9f1771815d98a4de9a1888f3692b92c52eacb10f5fe0d49ba"


def _manifest() -> list[dict]:
    with MANIFEST_CSV.open(newline="") as f:
        return list(csv.DictReader(f))


def _url(path: str) -> str:
    return f"https://raw.githubusercontent.com/{UPSTREAM}/{COMMIT}/{urllib.parse.quote(path)}"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(*, quiet: bool = False) -> bool:
    ok = True
    for row in _manifest():
        path = XU_DIR / row["path"]
        if not path.exists():
            ok = False
            if not quiet:
                print(f"missing: {path.relative_to(REPO_ROOT)}")
        elif _sha256(path) != row["sha256"]:
            ok = False
            if not quiet:
                print(f"hash mismatch: {path.relative_to(REPO_ROOT)}")
    return ok


def fetch(*, force: bool = False) -> bool:
    for row in _manifest():
        path = XU_DIR / row["path"]
        if path.exists() and not force and _sha256(path) == row["sha256"]:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"fetching {row['path']}")
        with urllib.request.urlopen(_url(row["path"]), timeout=60) as resp:
            data = resp.read()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise RuntimeError(f"hash mismatch for {row['path']} downloaded from {_url(row['path'])}")
        path.write_bytes(data)
    return verify()


def require() -> None:
    if not verify(quiet=True):
        raise SystemExit("Xu Dataset 1 files are missing or modified. Run: python -m psci_repro fetch-data")


def image_path(image_id: int) -> Path:
    for row in _manifest():
        if row["path"].startswith("Dataset_1/") and Path(row["path"]).stem == str(image_id):
            return XU_DIR / row["path"]
    raise KeyError(f"no Xu Dataset 1 image with id {image_id}")


def image_ids() -> list[int]:
    return sorted(int(Path(r["path"]).stem) for r in _manifest() if r["path"].startswith("Dataset_1/"))


@lru_cache(maxsize=1)
def labels() -> dict[int, int]:
    """Ground-truth PSCI level per image, parsed from Xu's `Evaluation (Dataset 1).md`."""
    require()
    text = (XU_DIR / EVAL_MD).read_text()
    img_re = re.compile(r'<img src="Dataset_1/(\d+)\.(?:jpg|png)"')
    level_re = re.compile(r"\*\*Level\s*\(\%\)\*\*\s*\|\s*\*\*Level\s*(\d+)\*\*", re.IGNORECASE)
    out: dict[int, int] = {}
    for chunk in re.split(r"^### Road Segment ", text, flags=re.MULTILINE)[1:]:
        img = img_re.search(chunk)
        level = level_re.search(chunk)
        if img and level:
            out[int(img.group(1))] = int(level.group(1))
    digest = hashlib.sha256(json.dumps(out, sort_keys=True).encode()).hexdigest()
    if digest != LABELS_SHA256:
        raise RuntimeError("parsed Xu labels do not match the labels used in the cached runs")
    return out


@lru_cache(maxsize=1)
def model5_prompt() -> dict:
    """Xu's Model 5 prompt, extracted from Model_5.ipynb.

    Returns {"rubric": str, "system": str, "before": [str], "after": [str]}: the system
    message, the user text parts sent before the image, and those sent after it.
    Whitespace-only lines inside the rubric are emptied, as in the copy used for the runs;
    the result is checked against PROMPT_SHA256.
    """
    require()
    cells = json.loads((XU_DIR / MODEL5_NB).read_text())["cells"]
    sources = ["".join(c["source"]) for c in cells if c["cell_type"] == "code"]
    rubric_src = next(s for s in sources if s.lstrip().startswith("road_grading_standards"))
    call_src = next(s for s in sources if "def get_road_condition_grade1" in s)

    rubric = ast.literal_eval(ast.parse(rubric_src).body[0].value)
    rubric = re.sub(r"(?m)^[ \t]+\n", "\n", rubric)

    messages = next(
        n.value for n in ast.walk(ast.parse(call_src))
        if isinstance(n, ast.Assign) and any(getattr(t, "id", None) == "messages" for t in n.targets)
    )
    system_msg, user_msg = messages.elts
    system = next(v.value for k, v in zip(system_msg.keys, system_msg.values) if k.value == "content")
    parts = next(v for k, v in zip(user_msg.keys, user_msg.values) if k.value == "content").elts

    before: list[str] = []
    after: list[str] = []
    target = before
    for part in parts:
        fields = {k.value: v for k, v in zip(part.keys, part.values)}
        if fields["type"].value == "image_url":
            target = after
            continue
        node = fields["text"]
        target.append(rubric if isinstance(node, ast.Name) else node.value)

    prompt = {"rubric": rubric, "system": system, "before": before, "after": after}
    digest = hashlib.sha256(
        json.dumps({"system": system, "before": before, "after": after}, ensure_ascii=False).encode()
    ).hexdigest()
    if digest != PROMPT_SHA256:
        raise RuntimeError("extracted Model 5 prompt does not match the prompt used in the cached runs")
    return prompt
