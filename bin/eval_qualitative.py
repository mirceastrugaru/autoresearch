#!/usr/bin/env python3
"""LLM-as-judge for qualitative autoresearch projects.

Two modes:
  1. Score mode (legacy): eval_qualitative.py <worker_dir> <autoresearch_dir>
     Scores a single worker's editable files against the rubric. Prints a number.

  2. Judge mode: eval_qualitative.py --judge <autoresearch_dir> <writeups_json> <roadmap_proposals>
     Full judge role: scores all write-ups, synthesizes the next main document,
     curates the roadmap. Outputs JSON to stdout.

Uses Claude Code (via Agent SDK) — no API key needed.
"""

import asyncio
import json
import os
import re
import sys
from pathlib import Path

from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage


def parse_section(text: str, heading: str) -> str:
    m = re.search(rf"## {heading}\s*\n(.*?)(\n## |\Z)", text, re.DOTALL)
    return m.group(1).strip() if m else ""


def parse_editable_files(text: str) -> list[str]:
    section = parse_section(text, "Editable files")
    if not section:
        return []
    return [l.strip().lstrip("- ") for l in section.splitlines() if l.strip()]


JUDGE_MODEL = os.environ.get("AUTORESEARCH_JUDGE_MODEL", "claude-sonnet-4-6")


async def run_judge(prompt: str) -> str:
    result_text = ""
    kwargs = dict(
        system_prompt="You are a strict evaluator and synthesizer. Respond ONLY with JSON. No other text.",
        permission_mode="bypassPermissions",
        max_turns=None,
        extra_args={"no-session-persistence": None},
    )
    if JUDGE_MODEL:
        kwargs["model"] = JUDGE_MODEL
    opts = ClaudeAgentOptions(**kwargs)
    async for msg in query(prompt=prompt, options=opts):
        if isinstance(msg, ResultMessage):
            result_text = msg.result or ""
    return result_text


def _parse_json(response: str) -> dict:
    text = response.strip()
    if text.startswith("```"):
        text = re.sub(r"^```\w*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def _re_derive_scores(result: dict) -> dict:
    """Re-derive final_score from gate verdicts — don't trust LLM's claim."""
    hard_failed = False
    soft_passed = 0
    for gate_name, gate in result.get("gates", {}).items():
        if gate.get("type") == "hard" and gate.get("result") == "fail":
            hard_failed = True
        if gate.get("type") == "soft" and gate.get("result") == "pass":
            soft_passed += 1
    final_score = 0 if hard_failed else soft_passed
    result["final_score"] = final_score
    result["hard_gate_failed"] = hard_failed
    result["soft_gates_passed"] = soft_passed
    return result


# ── Score mode (legacy, per-worker) ────────────────────────────────────────


def score_mode(worker_dir: Path, ar_dir: Path):
    program_text = (ar_dir / "program.md").read_text()
    rubric = parse_section(program_text, "Rubric")
    target = parse_section(program_text, "Target")
    editable_files = parse_editable_files(program_text)

    if not rubric:
        print("ERROR: No ## Rubric in program.md", file=sys.stderr)
        sys.exit(1)
    if not editable_files:
        print("ERROR: No editable files in program.md", file=sys.stderr)
        sys.exit(1)

    parts = []
    for f in editable_files:
        p = worker_dir / f
        if p.exists():
            parts.append(f"=== {f} ===\n{p.read_text()}")
        else:
            parts.append(f"=== {f} ===\n[NOT FOUND]")
    document = "\n\n".join(parts)

    prompt = f"""You are a precise, consistent evaluator. Apply each gate in the rubric as a checklist.

TARGET: {target}

RUBRIC:
{rubric}

DOCUMENT:
{document}

---

Evaluate every gate. Hard gate fail = final_score 0. Soft gates: count passes.

Sections marked "*Investigation pending*" are placeholders — do not penalize.

Respond ONLY with JSON:
{{
  "gates": {{
    "gate_name": {{"type": "hard|soft", "result": "pass|fail", "reason": "one sentence"}}
  }},
  "hard_gate_failed": true|false,
  "soft_gates_passed": N,
  "final_score": N
}}"""

    result = None
    last_err = None
    last_text = ""
    for attempt in (1, 2):
        response = asyncio.run(run_judge(
            prompt if attempt == 1
            else prompt + "\n\nYour previous response was not valid JSON. Respond with ONLY the JSON object."
        ))
        last_text = response
        try:
            result = _parse_json(response)
            break
        except json.JSONDecodeError as e:
            last_err = e
            continue

    if result is None:
        print(f"ERROR: JSON parse failed after retry: {last_err}", file=sys.stderr)
        print(f"Last response: {last_text[:500]}", file=sys.stderr)
        sys.exit(1)

    try:
        result = _re_derive_scores(result)
        (worker_dir / "eval_scores.json").write_text(json.dumps(result, indent=2))
        print(result["final_score"])
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


# ── Judge mode (full round judge) ─────────────────────────────────────────


def judge_mode(ar_dir: Path, writeups_json: str, roadmap_proposals: str):
    """Full judge: score write-ups + synthesize main document + curate roadmap."""
    program_text = (ar_dir / "program.md").read_text()
    rubric = parse_section(program_text, "Rubric")
    target = parse_section(program_text, "Target")
    editable_files = parse_editable_files(program_text)

    if not rubric:
        print("ERROR: No ## Rubric in program.md", file=sys.stderr)
        sys.exit(1)

    # Read current main document
    best_dir = ar_dir / "best"
    doc_parts = []
    for f in editable_files:
        p = best_dir / f
        if p.exists():
            doc_parts.append(f"=== {f} ===\n{p.read_text()}")
        else:
            doc_parts.append(f"=== {f} ===\n[EMPTY]")
    current_doc = "\n\n".join(doc_parts)

    # Read current roadmap
    roadmap = ""
    roadmap_path = ar_dir / "roadmap.md"
    if roadmap_path.exists():
        roadmap = roadmap_path.read_text()

    prompt_template_path = Path(__file__).parent.parent / "prompts" / "judge.md"
    prompt_template = prompt_template_path.read_text()
    prompt = prompt_template.format(
        target=target,
        rubric=rubric,
        current_doc=current_doc,
        writeups_json=writeups_json,
        roadmap=roadmap,
        roadmap_proposals=roadmap_proposals,
    )

    result = None
    last_err = None
    last_text = ""
    for attempt in (1, 2):
        response = asyncio.run(run_judge(
            prompt if attempt == 1
            else prompt + "\n\nYour previous response was not valid JSON. Respond with ONLY the JSON object."
        ))
        last_text = response
        try:
            result = _parse_json(response)
            break
        except json.JSONDecodeError as e:
            last_err = e
            continue

    if result is None:
        print(json.dumps({"error": f"JSON parse failed: {last_err}", "raw": last_text[:1000]}))
        sys.exit(1)

    # Re-derive scores for each worker
    for wid, wscores in result.get("scores", {}).items():
        result["scores"][wid] = _re_derive_scores(wscores)

    print(json.dumps(result))


# ── Main ───────────────────────────────────────────────────────────────────


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--judge":
        if len(sys.argv) < 5:
            print("Usage: eval_qualitative.py --judge <ar_dir> <writeups_json> <roadmap_proposals>",
                  file=sys.stderr)
            sys.exit(1)
        ar_dir = Path(sys.argv[2])
        writeups_json = sys.argv[3]
        roadmap_proposals = sys.argv[4]
        judge_mode(ar_dir, writeups_json, roadmap_proposals)
    elif len(sys.argv) >= 3:
        worker_dir = Path(sys.argv[1])
        ar_dir = Path(sys.argv[2])
        score_mode(worker_dir, ar_dir)
    else:
        print("Usage:", file=sys.stderr)
        print("  eval_qualitative.py <worker_dir> <autoresearch_dir>", file=sys.stderr)
        print("  eval_qualitative.py --judge <ar_dir> <writeups_json> <roadmap_proposals>", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
