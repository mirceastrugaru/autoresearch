"""Autoresearch findings summarizer.

Replaces the old summarize.md prompt that spawned a Claude Code instance
just to parse log.jsonl and write findings.md. No LLM needed.
"""

import json
from collections import Counter
from pathlib import Path

from bin.program_parser import read_or, read_log_entries


def summarize(ar_dir: Path) -> str:
    """Parse log.jsonl and write findings.md. Returns status message."""
    entries = read_log_entries(ar_dir)
    if not entries:
        (ar_dir / "findings.md").write_text("# Autoresearch Findings\n\nNo experiments run yet.\n")
        return "SUMMARY COMPLETE. 0 experiments summarized."

    # Stats
    total = len(entries)
    keeps = [e for e in entries if e.get("status") == "keep"]
    discards = [e for e in entries if e.get("status") == "discard"]
    crashes = [e for e in entries if e.get("status") in ("crash", "timeout")]

    best_score = max((e.get("score", 0) for e in entries), default=0)

    # Per-branch stats
    branches: dict[str, list[dict]] = {}
    for e in entries:
        b = e.get("branch", "main")
        branches.setdefault(b, []).append(e)

    # Experiment genealogy — chain of keeps
    genealogy = ["#0 (baseline)"]
    for e in sorted(keeps, key=lambda x: x.get("experiment_id", 0)):
        eid = e.get("experiment_id", "?")
        hyp = e.get("hypothesis", "")[:60]
        score = e.get("score", 0)
        genealogy.append(f'#{eid} "{hyp}" ({score:.1f})')

    # Common discard themes
    discard_hypotheses = [e.get("hypothesis", "") for e in discards if e.get("hypothesis")]
    theme_words = Counter()
    for h in discard_hypotheses:
        for word in h.lower().split():
            if len(word) > 4:
                theme_words[word] += 1
    common_themes = theme_words.most_common(5)

    # Roadmap
    roadmap_text = read_or(ar_dir / "roadmap.md", "")

    # Build findings.md
    lines = [
        "# Autoresearch Findings (auto-generated)\n",
        "## Stats",
        f"- Total experiments: {total} (keeps: {len(keeps)}, discards: {len(discards)}, "
        f"crashes: {len(crashes)})",
        f"- Best score: {best_score:.2f}\n",
        "## Experiment genealogy",
        " → ".join(genealogy) + "\n",
    ]

    # Per-branch
    lines.append("## Per-branch summary")
    for bname, bentries in sorted(branches.items()):
        bkeeps = sum(1 for e in bentries if e.get("status") == "keep")
        bdiscards = sum(1 for e in bentries if e.get("status") == "discard")
        bscore = max((e.get("score", 0) for e in bentries), default=0)
        lines.append(f"### {bname}")
        lines.append(f"- Experiments: {len(bentries)} (keeps: {bkeeps}, discards: {bdiscards})")
        lines.append(f"- Best score: {bscore:.2f}\n")

    # Kept changes
    lines.append("## Kept changes")
    if keeps:
        for e in keeps:
            eid = e.get("experiment_id", "?")
            parent = e.get("parent", "?")
            branch = e.get("branch", "?")
            hyp = e.get("hypothesis", "")[:100]
            score = e.get("score", 0)
            lines.append(f'- experiment {eid} [parent: #{parent}, {branch}]: "{hyp}" (score: {score:.1f})')
    else:
        lines.append("- none yet")
    lines.append("")

    # Common discard themes
    lines.append("## Common discard themes")
    if common_themes:
        for word, count in common_themes:
            lines.append(f"- {word} ({count} times)")
    else:
        lines.append("- none identified")
    lines.append("")

    # Convergence
    pivots = [b for b in branches if b.startswith("pivot-")]
    discard_streak = 0
    for e in reversed(entries):
        if e.get("status") == "discard":
            discard_streak += 1
        else:
            break

    lines.append("## Convergence notes")
    lines.append(f"- Pivots: {len(pivots)} ({', '.join(pivots) if pivots else 'none'})")
    lines.append(f"- Current discard streak: {discard_streak}")
    lines.append("")

    content = "\n".join(lines)
    (ar_dir / "findings.md").write_text(content)

    msg = f"SUMMARY COMPLETE. {total} experiments summarized."
    print(msg)
    return msg
