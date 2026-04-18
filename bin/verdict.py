"""Verdict generation for Autoresearch.

Reads log.jsonl, findings.md, and best document to produce a structured verdict.json.
"""

import json
import re
from pathlib import Path

from bin.program_parser import read_or, read_log_entries, parse_editable_files, read_target


def generate_verdict(ar_dir: Path) -> dict:
    """Generate verdict.json from log entries and current best document."""
    entries = read_log_entries(ar_dir)
    if not entries:
        return _empty_verdict(ar_dir)

    supportive_scores = [e["score"] for e in entries if e.get("stance") == "supportive" and e.get("score")]
    adversarial_scores = [e["score"] for e in entries if e.get("stance") == "adversarial" and e.get("score")]
    total_supportive = sum(supportive_scores) if supportive_scores else 0
    total_adversarial = sum(adversarial_scores) if adversarial_scores else 0
    total = total_supportive + total_adversarial or 1
    supportive_pct = int(round(total_supportive / total * 100))
    adversarial_pct = 100 - supportive_pct

    if abs(supportive_pct - adversarial_pct) < 10:
        leaning = "balanced"
    elif supportive_pct > adversarial_pct:
        leaning = "supportive"
    else:
        leaning = "adversarial"

    all_scores = [e["score"] for e in entries if e.get("score") is not None]
    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
    total_cost = sum(e.get("cost_usd", 0) for e in entries)

    rounds_seen = set()
    for e in entries:
        eid = str(e.get("experiment_id", ""))
        parts = eid.split("-")
        if len(parts) >= 3 and parts[0] == "exp":
            try:
                rounds_seen.add(int(parts[1]))
            except ValueError:
                pass
    num_rounds = len(rounds_seen) if rounds_seen else 1

    findings = _extract_findings(ar_dir, entries)
    supportive_args = _extract_arguments(entries, "supportive")
    adversarial_args = _extract_arguments(entries, "adversarial")
    next_actions = _extract_next_actions(ar_dir)

    if leaning == "balanced":
        headline = "Balanced — evidence on both sides."
        subtitle = "Supportive and adversarial evidence are comparable."
    elif leaning == "supportive":
        headline = "Leans supportive — with caveats."
        subtitle = "Evidence tilts toward the directions investigated."
    else:
        headline = "Leans adversarial — with caveats."
        subtitle = "Evidence challenges the directions investigated."

    verdict = {
        "leaning": leaning,
        "tension": {"supportive": supportive_pct, "adversarial": adversarial_pct},
        "headline": headline,
        "subtitle": subtitle,
        "stats": {
            "writeups": len(entries),
            "avgScore": round(avg_score, 2),
            "rounds": num_rounds,
            "cost": round(total_cost, 2),
        },
        "findings": findings,
        "arguments": {"supportive": supportive_args, "adversarial": adversarial_args},
        "nextActions": next_actions,
    }

    verdict_path = ar_dir / "verdict.json"
    verdict_path.write_text(json.dumps(verdict, indent=2))
    return verdict


def _empty_verdict(ar_dir: Path) -> dict:
    return {
        "leaning": "balanced",
        "tension": {"supportive": 50, "adversarial": 50},
        "headline": "No experiments run yet.",
        "subtitle": "",
        "stats": {"writeups": 0, "avgScore": 0, "rounds": 0, "cost": 0},
        "findings": [],
        "arguments": {"supportive": [], "adversarial": []},
        "nextActions": [],
    }


def _strip_md(text: str) -> str:
    """Strip markdown formatting, stance prefixes, and review flags from text."""
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)
    text = re.sub(r'\*([^*]+)\*', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    text = re.sub(r'^HYPOTHESIS:\s*', '', text.strip())
    text = re.sub(r'^\[FLAGGED FOR REVIEW\]\s*', '', text.strip())
    return text.strip()


def _extract_findings(ar_dir: Path, entries: list[dict]) -> list[dict]:
    """Extract findings from kept experiments' key evidence."""
    findings = []

    # Get kept experiments — these have the actual research findings
    kept = [e for e in entries if e.get("status") == "keep" and e.get("score", 0) > 0]
    kept.sort(key=lambda e: e.get("score", 0), reverse=True)

    for entry in kept[:6]:
        hypothesis = _strip_md(entry.get("hypothesis", ""))
        summary = _strip_md(entry.get("summary", ""))
        stance = entry.get("stance", "")
        score = entry.get("score", 0)

        if hypothesis:
            lead = hypothesis.split()[0].rstrip(".:,") if hypothesis.split() else ""
            text = hypothesis
            if summary and summary != hypothesis:
                text = summary[:300] if len(summary) > len(hypothesis) else hypothesis

            findings.append({
                "leadWord": lead,
                "text": text,
                "sourceWriteups": [str(entry.get("experiment_id", ""))],
            })

    # If no kept experiments, fall back to best document sections
    if not findings:
        findings = _extract_findings_from_doc(ar_dir)

    return findings[:8]


def _extract_findings_from_doc(ar_dir: Path) -> list[dict]:
    """Extract findings from section headings in the best document."""
    editable = parse_editable_files(ar_dir)
    for f in editable:
        best_path = ar_dir / "best" / f
        if best_path.exists():
            text = best_path.read_text()
            findings = []
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("## ") and not line.startswith("## Table") and not line.startswith("## Reference"):
                    heading = _strip_md(line[3:].strip())
                    if heading and len(heading) > 5:
                        lead = heading.split()[0].rstrip(".:,")
                        findings.append({
                            "leadWord": lead,
                            "text": heading,
                            "sourceWriteups": [],
                        })
            if findings:
                return findings[:8]
    return []


def _extract_arguments(entries: list[dict], stance: str) -> list[dict]:
    """Extract strongest arguments for a stance from log entries."""
    stance_entries = [e for e in entries if e.get("stance") == stance and e.get("score", 0) > 0]
    stance_entries.sort(key=lambda e: e.get("score", 0), reverse=True)

    args = []
    seen_titles = set()
    for entry in stance_entries[:5]:
        hypothesis = _strip_md(entry.get("hypothesis", ""))
        summary = _strip_md(entry.get("summary", ""))
        if not hypothesis:
            continue

        # Take only the first meaningful line
        first_line = hypothesis.split("\n")[0].strip()
        if not first_line:
            first_line = hypothesis.replace("\n", " ").strip()
        title = first_line[:120]
        if title in seen_titles:
            continue
        seen_titles.add(title)

        evidence = summary[:250] if summary and summary != hypothesis else ""

        args.append({
            "title": title,
            "score": entry.get("score", 0),
            "evidence": evidence,
            "sourceWriteups": [str(entry.get("experiment_id", ""))],
        })

    return args


def _extract_next_actions(ar_dir: Path) -> list[dict]:
    """Extract next actions from roadmap's uncovered directions."""
    from bin.program_parser import parse_roadmap, build_coverage_matrix

    dirs = parse_roadmap(ar_dir)
    if not dirs:
        return []

    coverage = build_coverage_matrix(ar_dir, dirs)
    uncovered = [d for d in dirs if coverage.get(d["id"], 0) == 0]

    actions = []
    for d in uncovered[:5]:
        priority = "high" if d["priority"] <= 2 else "med" if d["priority"] <= 4 else "low"
        clean_title = _strip_md(d["title"])
        actions.append({
            "text": f"Investigate: {clean_title[:120]}",
            "priority": priority,
            "rationale": clean_title,
        })

    return actions
