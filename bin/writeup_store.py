"""Writeup persistence for Autoresearch.

Copies writeup files from worker directories to ar_dir/writeups/<exp_id>/
before worker cleanup. Also reconstructs writeup metadata from log.jsonl
for runs that completed before persistence was added.
"""

import json
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

        exp_id_path = wdir / "experiment_id.txt"
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

        # Also save stance info
        stance_file = dest / "stance.txt"
        if not stance_file.exists():
            # Try to determine from log
            log_path = ar_dir / "log.jsonl"
            if log_path.exists():
                for line in log_path.read_text().strip().splitlines():
                    try:
                        entry = json.loads(line)
                        if str(entry.get("experiment_id")) == str(exp_id):
                            stance_file.write_text(entry.get("stance", "unknown"))
                            break
                    except json.JSONDecodeError:
                        continue


def list_writeups(ar_dir: Path) -> list[dict]:
    """List all writeups, from persisted files or reconstructed from log."""
    writeups_dir = ar_dir / "writeups"
    log_entries = _read_log(ar_dir)

    result = []

    if writeups_dir.exists():
        for exp_dir in sorted(writeups_dir.iterdir()):
            if not exp_dir.is_dir():
                continue
            wp = _load_persisted_writeup(exp_dir, log_entries)
            if wp:
                result.append(wp)
    elif log_entries:
        # Reconstruct from log only
        for entry in log_entries:
            result.append(_reconstruct_from_log(entry))

    return result


def get_writeup(ar_dir: Path, writeup_id: str) -> dict | None:
    """Get a single writeup by ID."""
    writeups_dir = ar_dir / "writeups"
    log_entries = _read_log(ar_dir)

    # Try persisted
    if writeups_dir.exists():
        exp_dir = writeups_dir / writeup_id
        if exp_dir.exists():
            return _load_persisted_writeup(exp_dir, log_entries, full=True)

    # Reconstruct from log
    for entry in log_entries:
        if str(entry.get("experiment_id")) == writeup_id:
            return _reconstruct_from_log(entry, full=True)

    return None


def _read_log(ar_dir: Path) -> list[dict]:
    log_path = ar_dir / "log.jsonl"
    if not log_path.exists():
        return []
    entries = []
    for line in log_path.read_text().strip().splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def _load_persisted_writeup(exp_dir: Path, log_entries: list[dict], full: bool = False) -> dict | None:
    exp_id = exp_dir.name

    # Find matching log entry
    log_entry = None
    for entry in log_entries:
        if str(entry.get("experiment_id")) == exp_id:
            log_entry = entry
            break

    hypothesis = _read_file(exp_dir / "hypothesis.txt")
    writeup_text = _read_file(exp_dir / "writeup.md")
    summary = _read_file(exp_dir / "summary.txt")
    stance = _read_file(exp_dir / "stance.txt") or (log_entry.get("stance", "") if log_entry else "")
    score = float(_read_file(exp_dir / "score.txt") or "0") if (exp_dir / "score.txt").exists() else None

    # Override with log entry data if available
    if log_entry:
        if score is None:
            score = log_entry.get("score", 0)
        status = log_entry.get("status", "unknown")
        direction = log_entry.get("assigned_direction", "")
        round_num = _infer_round(exp_id, log_entries)
        worker_id = f"w{log_entry.get('worker', '?')}"
    else:
        status = "unknown"
        direction = ""
        round_num = 0
        worker_id = "?"

    rubric_breakdown = None
    eval_scores_path = exp_dir / "eval_scores.json"
    if eval_scores_path.exists():
        try:
            rubric_breakdown = json.loads(eval_scores_path.read_text())
        except json.JSONDecodeError:
            pass

    excerpt = (writeup_text[:200] + "...") if writeup_text and len(writeup_text) > 200 else (writeup_text or hypothesis or summary or "")

    result = {
        "id": exp_id,
        "workerId": worker_id,
        "round": round_num,
        "stance": stance,
        "dir": direction,
        "score": score or 0,
        "status": status,
        "excerpt": excerpt,
    }

    if full:
        result["content"] = writeup_text or summary or hypothesis or ""
        result["rubricBreakdown"] = rubric_breakdown
        result["hypothesis"] = hypothesis

    return result


def _reconstruct_from_log(entry: dict, full: bool = False) -> dict:
    """Reconstruct writeup metadata from log entry alone."""
    exp_id = str(entry.get("experiment_id", "?"))
    hypothesis = entry.get("hypothesis", "")
    summary = entry.get("summary", "")

    result = {
        "id": exp_id,
        "workerId": f"w{entry.get('worker', '?')}",
        "round": _infer_round_from_entry(entry),
        "stance": entry.get("stance", ""),
        "dir": entry.get("assigned_direction", ""),
        "score": entry.get("score", 0),
        "status": entry.get("status", "unknown"),
        "excerpt": hypothesis[:200] if hypothesis else summary[:200] if summary else "",
    }

    if full:
        result["content"] = hypothesis or summary or ""
        result["rubricBreakdown"] = None
        result["hypothesis"] = hypothesis

    return result


def _infer_round(exp_id: str, log_entries: list[dict]) -> int:
    """Infer round number from experiment ID pattern (exp-R-W-hash) or position."""
    parts = exp_id.split("-")
    if len(parts) >= 3 and parts[0] == "exp":
        try:
            return int(parts[1])
        except ValueError:
            pass

    # Fall back to position-based inference
    for entry in log_entries:
        if str(entry.get("experiment_id")) == exp_id:
            return _infer_round_from_entry(entry)
    return 0


def _infer_round_from_entry(entry: dict) -> int:
    """Infer round from experiment ID or position."""
    exp_id = str(entry.get("experiment_id", ""))
    parts = exp_id.split("-")
    if len(parts) >= 3 and parts[0] == "exp":
        try:
            return int(parts[1])
        except ValueError:
            pass
    # For numeric experiment IDs, estimate: round = ceil(exp_id / parallelism)
    try:
        eid = int(exp_id)
        return (eid + 1) // 2  # Assumes parallelism=2
    except (ValueError, TypeError):
        return 0


def _read_file(path: Path) -> str:
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        return ""
