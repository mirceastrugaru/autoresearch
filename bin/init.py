"""Autoresearch project initialization.

Replaces the old init.md prompt that spawned a Claude Code instance
just to do file operations. No LLM needed — this is pure scaffolding.
"""

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bin.program_parser import (
    parse_editable_files,
    parse_program_directions,
    read_eval_mode,
    read_or,
    read_state,
    read_target,
    register_direction,
    write_state,
)


def init_project(
    project_dir: Path,
    ar_dir: Path,
    eval_mode: str,
    parallelism: int,
) -> str:
    """Initialize an autoresearch project. Returns status message.

    If state.json exists, resumes. Otherwise scaffolds from scratch.
    """
    state_file = ar_dir / "state.json"

    # Resume
    if state_file.exists():
        state = read_state(ar_dir)
        msg = (f"Resumed: round {state.get('round', 0)}, "
               f"{state.get('experiment_count', 0)} experiments, "
               f"best {state.get('best_score', 0)}")
        print(msg)
        print("INIT RESUMED.")
        return msg

    # Fresh init
    program_path = ar_dir / "program.md"
    if not program_path.exists():
        msg = "INIT FAILED: program.md not found"
        print(msg)
        return msg

    program_text = program_path.read_text()

    # Validate eval.sh for quantitative mode
    if eval_mode == "quantitative":
        eval_path = ar_dir / "eval.sh"
        if not eval_path.exists():
            msg = "INIT FAILED: eval.sh not found"
            print(msg)
            return msg
        eval_path.chmod(0o755)

    # Extract config from program.md
    editable_files = parse_editable_files(ar_dir)
    directions = parse_program_directions(ar_dir)

    # Scaffold best/ and branches/main/
    for base in [ar_dir / "best", ar_dir / "branches" / "main"]:
        base.mkdir(parents=True, exist_ok=True)
        for rel_path in editable_files:
            dest = base / rel_path
            dest.parent.mkdir(parents=True, exist_ok=True)
            src = project_dir / rel_path
            if src.exists():
                shutil.copy2(src, dest)
            elif not dest.exists():
                _create_baseline(dest, rel_path, directions, read_target(ar_dir), eval_mode)

    # Validate baseline
    if eval_mode == "quantitative":
        score = _run_eval(ar_dir)
        if score is None:
            msg = "INIT FAILED: eval.sh did not produce a number"
            print(msg)
            return msg
    else:
        score = 0

    # Write best_score.txt
    (ar_dir / "best_score.txt").write_text(f"{score}\n")

    # Create empty log.jsonl
    (ar_dir / "log.jsonl").write_text("")

    # Create findings.md
    (ar_dir / "findings.md").write_text("# Findings\n\nNo experiments yet.\n")

    # Create directions.jsonl registry and roadmap.md
    (ar_dir / "directions.jsonl").write_text("")
    roadmap_lines = ["# Roadmap\n", "## Directions"]
    for i, d in enumerate(directions, 1):
        title = d.get("fullText", d.get("text", ""))
        register_direction(ar_dir, d["id"], title, parent_id=None, source="program.md")
        roadmap_lines.append(f"{i}. [{d['id']}] {title}")
    (ar_dir / "roadmap.md").write_text("\n".join(roadmap_lines) + "\n")

    # Create branches.jsonl
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    branch_entry = {
        "branch": "main",
        "forked_from": "baseline",
        "status": "active",
        "created_at": now,
        "experiments": 0,
        "best_score": score,
    }
    (ar_dir / "branches.jsonl").write_text(json.dumps(branch_entry) + "\n")

    # Write state.json
    state = {
        "version": 1,
        "round": 0,
        "experiment_count": 0,
        "best_score": score,
        "active_branch": "main",
        "discard_streak": 0,
        "last_promoted_experiment": 0,
        "best_unchanged_count": 0,
        "last_pivot_experiment": 0,
        "eval_mode": eval_mode,
        "parallelism": parallelism,
    }
    write_state(ar_dir, state)

    msg = f"INIT COMPLETE. Baseline score: {score}"
    print(msg)
    return msg


def _run_eval(ar_dir: Path) -> float | None:
    """Run eval.sh against best/ and return the score, or None on failure."""
    try:
        r = subprocess.run(
            ["bash", str(ar_dir / "eval.sh"), str(ar_dir / "best")],
            capture_output=True, text=True, timeout=120,
        )
        for line in reversed(r.stdout.strip().splitlines()):
            try:
                return float(line.strip())
            except ValueError:
                continue
        return None
    except Exception as e:
        print(f"INIT FAILED: eval.sh error: {e}")
        return None


def _create_baseline(dest: Path, rel_path: str, directions: list[dict], target: str, eval_mode: str):
    """Create a substantive baseline file for qualitative projects."""
    if eval_mode != "qualitative":
        dest.write_text("")
        return

    lines = [f"# {_title_from_path(rel_path)}\n"]
    if target:
        lines.append(f"{target}\n")

    for d in directions:
        title = d.get("text", d.get("fullText", "Untitled"))
        lines.append(f"## {title}\n")
        lines.append("*Investigation pending — no findings yet; this section will be populated by research rounds.*\n")

    # Pad to minimum 500 words for qualitative baselines
    content = "\n".join(lines)
    word_count = len(content.split())
    if word_count < 500:
        lines.append("\n## Methodology\n")
        lines.append("*Investigation pending — no findings yet; this section will be populated by research rounds.*\n")
        lines.append("\n## Synthesis\n")
        lines.append("*Investigation pending — no findings yet; this section will be populated by research rounds.*\n")

    dest.write_text("\n".join(lines))


def _title_from_path(rel_path: str) -> str:
    """Derive a document title from a file path."""
    name = Path(rel_path).stem
    return name.replace("-", " ").replace("_", " ").title()
