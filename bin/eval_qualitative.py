#!/usr/bin/env python3
"""LLM-as-judge evaluator for qualitative autoresearch projects.

Usage: eval_qualitative.py <worker_dir> <autoresearch_dir>

Uses Claude Code (via Agent SDK) to evaluate documents against hard/soft gates.
No API key needed — uses Claude Code's own auth.
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


JUDGE_MODEL = os.environ.get("AUTORESEARCH_JUDGE_MODEL", os.environ.get("AUTORESEARCH_MODEL", None))


async def run_judge(prompt: str) -> str:
    result_text = ""
    opts = ClaudeAgentOptions(
        system_prompt="You are a strict evaluator. Respond ONLY with JSON. No other text.",
        permission_mode="bypassPermissions",
        max_turns=1,
        extra_args={"no-session-persistence": None},
    )
    if JUDGE_MODEL:
        opts.model = JUDGE_MODEL
    async for msg in query(
        prompt=prompt,
        options=opts,
    ):
        if isinstance(msg, ResultMessage):
            result_text = msg.result or ""
    return result_text


def main():
    if len(sys.argv) < 3:
        print("Usage: eval_qualitative.py <worker_dir> <autoresearch_dir>", file=sys.stderr)
        sys.exit(1)

    worker_dir = Path(sys.argv[1])
    ar_dir = Path(sys.argv[2])

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

    prompt = f"""Evaluate this document against the rubric. Be harsh.

TARGET: {target}

RUBRIC:
{rubric}

DOCUMENT:
{document}

For each gate in the rubric, output pass or fail with a one-sentence reason.
If a gate is marked "hard", failing it means final score = 0 regardless of other gates.
For soft gates, count passes. Final score = number of soft gates passed.

Respond ONLY with JSON:
{{
  "gates": {{
    "gate_name": {{"type": "hard|soft", "result": "pass|fail", "reason": "one sentence"}}
  }},
  "hard_gate_failed": true|false,
  "soft_gates_passed": N,
  "final_score": N
}}

If any hard gate failed, final_score MUST be 0.
Otherwise final_score = soft_gates_passed."""

    response = asyncio.run(run_judge(prompt))

    try:
        # Strip markdown code blocks if present
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```\w*\n?", "", text)
            text = re.sub(r"\n?```$", "", text)

        result = json.loads(text)

        # Enforce hard gate logic ourselves
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
        (worker_dir / "eval_scores.json").write_text(json.dumps(result, indent=2))

        print(final_score)

    except json.JSONDecodeError as e:
        print(f"ERROR: JSON parse failed: {e}", file=sys.stderr)
        print(f"Response: {text[:500]}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
