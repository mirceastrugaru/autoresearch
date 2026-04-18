"""Writeup persistence for Autoresearch.

Copies writeup files from worker directories to ar_dir/writeups/<exp_id>/
before worker cleanup.
"""

import shutil
from pathlib import Path


PERSIST_FILES = [
    "writeup.md",
    "hypothesis.txt",
    "eval_scores.json",
    "summary.txt",
    "score.txt",
    "roadmap_append.md",
]


def persist_writeups(ar_dir: Path, parallelism: int, round_num: int):
    """Copy writeup files from worker dirs to ar_dir/writeups/ before cleanup."""
    writeups_dir = ar_dir / "writeups"
    writeups_dir.mkdir(exist_ok=True)

    for i in range(1, parallelism + 1):
        wdir = ar_dir / "workers" / f"worker-{i}"
        if not wdir.exists():
            continue

        exp_id_path = wdir / "experiment_id_output.txt"
        if not exp_id_path.exists():
            continue
        exp_id = exp_id_path.read_text().strip()
        if not exp_id:
            continue

        dest = writeups_dir / exp_id
        dest.mkdir(parents=True, exist_ok=True)

        for fname in PERSIST_FILES:
            src = wdir / fname
            if src.exists():
                shutil.copy2(src, dest / fname)
