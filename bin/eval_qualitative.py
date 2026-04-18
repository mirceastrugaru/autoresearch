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

    prompt = f"""You are the judge for an autoresearch project. You have four jobs. Job 3 (roadmap curation) is the most important — the quality of the roadmap determines what gets investigated next.

TARGET: {target}

RUBRIC:
{rubric}

CURRENT MAIN DOCUMENT:
{current_doc}

WORKER WRITE-UPS THIS ROUND:
{writeups_json}

CURRENT ROADMAP:
{roadmap}

WORKER ROADMAP PROPOSALS:
{roadmap_proposals}

---

Respond with a single JSON object containing four sections.

### Job 1: Score each write-up
Apply the rubric to each write-up. Hard gate fail = score 0. Soft gates: count passes.

### Job 2: Synthesize the next main document
Read all supportive write-ups (evidence consistent with directions) and adversarial write-ups (evidence inconsistent). Produce the next version of the main document that:
- Incorporates consistent evidence into the appropriate sections.
- Addresses inconsistent evidence — either with counter-evidence, acknowledging it as a limitation, or revising claims.
- Does not suppress evidence from either stance.
- Maintains all existing content that wasn't contradicted.
- ONLY includes sections with actual evidence. No placeholder sections — those belong in the meta document.
- Each worker's contribution: at most 150 words. State the finding, the strongest evidence, and the source. 50 words is better than 150 if the point is clear.
One editable file per entry in the editable files list EXCEPT the meta document (see Job 4).

### Job 3: Curate the roadmap
This is your most important job. The roadmap drives what gets investigated next. Do it well.

Read worker proposals. For each proposal, evaluate:
1. **Is it specific enough to assign?** A worker receiving this direction must know exactly what to investigate and what evidence to look for. "Investigate X" is not assignable. "Investigate X by checking Y and Z — if true, it means W" is.
2. **Is it already covered?** Check both the existing roadmap and this round's write-ups. If a direction has been deeply researched, mark it done — don't keep it.
3. **Does it matter?** Would confirming or disconfirming this direction change the analysis? If not, drop it.

Then produce the updated roadmap:
- Drop duplicates and covered directions.
- Add proposals that pass the three checks above.
- Reorder by impact (directions that would most change the analysis first).
- If a proposal is promising but too vague, rewrite it to be specific before adding.
- If uncertain, add with "[FLAGGED FOR REVIEW]" prefix.
- Format as a flat numbered list under `## Directions`.

### Job 4: Update the meta document
Track the research process: directions assigned, coverage, round log (workers, stance, direction, score, key finding, hard gate pass/fail), remaining directions, failures, cost.

Respond ONLY with JSON:
{{
  "scores": {{
    "worker_id": {{
      "gates": {{
        "gate_name": {{"type": "hard|soft", "result": "pass|fail", "reason": "one sentence"}}
      }},
      "hard_gate_failed": true|false,
      "soft_gates_passed": N,
      "final_score": N
    }}
  }},
  "documents": {{
    "editable/file/path.md": "full updated document content"
  }},
  "meta": "full meta document markdown",
  "roadmap": "full updated roadmap markdown"
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
