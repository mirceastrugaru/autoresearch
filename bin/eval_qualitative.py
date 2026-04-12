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


JUDGE_MODEL = os.environ.get("AUTORESEARCH_JUDGE_MODEL", "claude-sonnet-4-6")


async def run_judge(prompt: str) -> str:
    result_text = ""
    opts = ClaudeAgentOptions(
        system_prompt="You are a strict evaluator. Respond ONLY with JSON. No other text.",
        permission_mode="bypassPermissions",
        max_turns=None,
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

    prompt = f"""You are a precise, consistent research evaluator. Your job is to reward real investigative work and penalize vague, unsourced, or fabricated content. Apply each gate as a checklist — the same document should always get the same score. Evaluate the document below against each gate in the rubric.

TARGET: {target}

RUBRIC:
{rubric}

DOCUMENT:
{document}

---

EVALUATION INSTRUCTIONS:

For each gate, apply the specific test below. Do not interpret loosely — if the test is not clearly met, it fails.

HARD GATES — if either fails, final_score = 0, stop counting soft gates:

correctness:
  FAIL if ANY of these are true:
  - A URL is cited but the domain or path does not plausibly match the claimed content
  - A statistic is given without a traceable source (no URL, no document name, no publication)
  - A certification level is stated (e.g. "ASIL D", "SIL 4", "Class C") without citing the specific certification document or notified body
  - A claim is internally contradicted elsewhere in the document
  PASS only if every specific factual claim is backed by a named, plausible, verifiable source

evidence:
  FAIL if ANY of these are true:
  - A non-trivial claim (adoption figures, certification status, market position, technical specs) has no citation at all
  - A citation points only to a vendor's own marketing page with no corroborating independent source
  - A section says "TBD", "limited public data", "not documented" for a topic the rubric requires coverage of
  PASS only if every major claim in every required section has a specific, named, non-marketing source

SOFT GATES — count how many pass:

For each soft gate, answer YES or NO to the specific question:

technical_specificity:
  Does the document contain at least 5 concrete technical numbers (memory footprints in KB/MB, specific MCU families by name, commit counts, star counts with retrieval date, version numbers, benchmark figures)?
  YES = pass, NO = fail

comparative_insight:
  Does the document explain *why* differences between frameworks matter for a specific regulated project — not just that differences exist, but the concrete consequence (e.g. certification timeline, SOUP dossier scope, tool qualification cost)?
  YES = pass, NO = fail

analytical_reasoning:
  Does the document derive conclusions from multiple evidence points — not just list facts but connect them into an argument with a stated conclusion?
  YES = pass, NO = fail

causal_implications:
  Does the document trace at least 2 adoption patterns to their root causes with evidence (e.g. why a framework dominates or is absent in a specific domain, traced to a specific technical or regulatory constraint)?
  YES = pass, NO = fail

investigative_effort:
  Does the document contain at least 3 of: (a) actual quoted forum/Reddit posts with usernames or thread links, (b) GitHub repo stats with retrieval date, (c) named certification document or certificate number, (d) named real-world product deployment, (e) job posting counts with source and date?
  YES = pass, NO = fail

trend_analysis:
  Does the document show directional movement over time with data — not just current state, but at least 2 data points at different times (e.g. star counts in 2023 vs 2025, job postings trending up/down, conference talk counts by year)?
  YES = pass, NO = fail

regulated_domain_coverage:
  Does the document provide framework-specific certification status (pass/fail/roadmap with source) for at least 5 distinct regulated domains from this list: automotive/ISO 26262, aviation/DO-178C, medical/IEC 62304, railway/EN 50128, industrial/IEC 61508, nuclear/IEC 61513, defense/MIL-STD, marine/DNV?
  YES = pass, NO = fail

---

Respond ONLY with JSON. No preamble, no explanation outside the JSON:
{{
  "gates": {{
    "gate_name": {{"type": "hard|soft", "result": "pass|fail", "reason": "one sentence citing specific evidence or specific deficiency"}}
  }},
  "hard_gate_failed": true|false,
  "soft_gates_passed": N,
  "final_score": N
}}

If any hard gate failed, final_score MUST be 0.
Otherwise final_score = number of soft gates with result=pass."""

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
