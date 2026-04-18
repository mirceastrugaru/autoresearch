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


def _load_prompt(name: str) -> str:
    return (Path(__file__).parent.parent / "prompts" / name).read_text()


def _call_judge_json(prompt: str, label: str) -> dict | None:
    """Call the judge LLM and parse JSON response. Retries once on parse failure."""
    last_err = None
    last_text = ""
    for attempt in (1, 2):
        response = asyncio.run(run_judge(
            prompt if attempt == 1
            else prompt + "\n\nYour previous response was not valid JSON. Respond with ONLY the JSON object."
        ))
        last_text = response
        try:
            return _parse_json(response)
        except json.JSONDecodeError as e:
            last_err = e
            print(f"  {label}: JSON parse attempt {attempt} failed: {e}", file=sys.stderr)
            continue
    print(f"  {label}: JSON parse failed after retry: {last_err}", file=sys.stderr)
    return None


def _call_judge_text(prompt: str, label: str) -> str | None:
    """Call the judge LLM and return raw text response."""
    response = asyncio.run(run_judge(prompt))
    if not response.strip():
        print(f"  {label}: empty response", file=sys.stderr)
        return None
    return response.strip()


def judge_mode(ar_dir: Path, writeups_json: str, roadmap_proposals: str):
    """Full judge: 4 sequential calls — score, synthesize, roadmap, meta."""
    program_text = (ar_dir / "program.md").read_text()
    rubric = parse_section(program_text, "Rubric")
    target = parse_section(program_text, "Target")
    editable_files = parse_editable_files(program_text)

    if not rubric:
        print("ERROR: No ## Rubric in program.md", file=sys.stderr)
        sys.exit(1)

    best_dir = ar_dir / "best"
    doc_parts = []
    for f in editable_files:
        p = best_dir / f
        if p.exists():
            doc_parts.append(f"=== {f} ===\n{p.read_text()}")
        else:
            doc_parts.append(f"=== {f} ===\n[EMPTY]")
    current_doc = "\n\n".join(doc_parts)

    roadmap = ""
    roadmap_path = ar_dir / "roadmap.md"
    if roadmap_path.exists():
        roadmap = roadmap_path.read_text()

    current_meta = ""
    meta_path = ar_dir / "meta.md"
    if meta_path.exists():
        current_meta = meta_path.read_text()

    result = {"scores": {}, "documents": {}, "meta": "", "roadmap": ""}

    # ── Call 1: Score write-ups ──
    score_prompt = _load_prompt("judge_score.md").format(
        target=target, rubric=rubric, writeups_json=writeups_json,
    )
    scores = _call_judge_json(score_prompt, "SCORE")
    if scores:
        for wid, wscores in scores.items():
            result["scores"][wid] = _re_derive_scores(wscores)

    # Build round summary for downstream calls
    writeups = json.loads(writeups_json)
    summary_lines = []
    for wid, wdata in writeups.items():
        score_info = result["scores"].get(wid, {})
        s = score_info.get("final_score", "?")
        hard_fail = score_info.get("hard_gate_failed", False)
        summary_lines.append(
            f"- {wid} ({wdata.get('stance', '?')}, direction: {wdata.get('direction', '?')}): "
            f"score={s}, hard_fail={hard_fail}, hypothesis: {wdata.get('hypothesis', '?')}"
        )
    round_summary = "\n".join(summary_lines)

    # Annotate writeups with scores for the synthesizer
    writeups_with_scores = writeups_json
    if scores:
        annotated = json.loads(writeups_json)
        for wid in annotated:
            if wid in result["scores"]:
                annotated[wid]["score"] = result["scores"][wid].get("final_score", 0)
                annotated[wid]["hard_gate_failed"] = result["scores"][wid].get("hard_gate_failed", False)
        writeups_with_scores = json.dumps(annotated)

    # ── Call 2: Synthesize document ──
    synth_prompt = _load_prompt("judge_synthesize.md").format(
        target=target, current_doc=current_doc,
        writeups_with_scores=writeups_with_scores,
    )
    documents = _call_judge_json(synth_prompt, "SYNTHESIZE")
    if documents:
        result["documents"] = documents

    # ── Call 3: Curate roadmap ──
    roadmap_prompt = _load_prompt("judge_roadmap.md").format(
        target=target, roadmap=roadmap,
        roadmap_proposals=roadmap_proposals or "(none)",
        round_summary=round_summary,
    )
    new_roadmap = _call_judge_text(roadmap_prompt, "ROADMAP")
    if new_roadmap:
        result["roadmap"] = new_roadmap

    # ── Call 4: Update meta ──
    meta_prompt = _load_prompt("judge_meta.md").format(
        target=target, current_meta=current_meta or "(no meta document yet)",
        round_summary=round_summary,
        roadmap=result["roadmap"] or roadmap,
    )
    new_meta = _call_judge_text(meta_prompt, "META")
    if new_meta:
        result["meta"] = new_meta

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
