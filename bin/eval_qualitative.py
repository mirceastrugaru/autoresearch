#!/usr/bin/env python3
"""LLM-as-judge evaluator for qualitative autoresearch projects.

Usage: eval_qualitative.py <worker_dir> <autoresearch_dir>

Reads the rubric from program.md, reads the editable files from the worker
directory, and uses Claude to score them. Prints a single number to stdout.
"""

import json
import os
import re
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("ERROR: anthropic package not installed. pip install anthropic", file=sys.stderr)
    sys.exit(1)


def parse_rubric(program_text: str) -> str:
    """Extract the Rubric section from program.md."""
    m = re.search(r"## Rubric\s*\n(.*?)(\n## |\Z)", program_text, re.DOTALL)
    if not m:
        print("ERROR: No ## Rubric section found in program.md", file=sys.stderr)
        sys.exit(1)
    return m.group(1).strip()


def parse_editable_files(program_text: str) -> list[str]:
    """Extract editable files list from program.md."""
    m = re.search(r"## Editable files\s*\n(.*?)(\n##|\Z)", program_text, re.DOTALL)
    if not m:
        return []
    return [
        line.strip().lstrip("- ")
        for line in m.group(1).strip().splitlines()
        if line.strip()
    ]


def parse_target(program_text: str) -> str:
    """Extract the Target section from program.md."""
    m = re.search(r"## Target\s*\n(.*?)(\n## |\Z)", program_text, re.DOTALL)
    return m.group(1).strip() if m else "Unknown target"


def main():
    if len(sys.argv) < 3:
        print("Usage: eval_qualitative.py <worker_dir> <autoresearch_dir>", file=sys.stderr)
        sys.exit(1)

    worker_dir = Path(sys.argv[1])
    ar_dir = Path(sys.argv[2])

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    # Read program.md
    program_path = ar_dir / "program.md"
    if not program_path.exists():
        print("ERROR: program.md not found", file=sys.stderr)
        sys.exit(1)
    program_text = program_path.read_text()

    rubric = parse_rubric(program_text)
    target = parse_target(program_text)
    editable_files = parse_editable_files(program_text)

    if not editable_files:
        print("ERROR: No editable files listed in program.md", file=sys.stderr)
        sys.exit(1)

    # Read the content of editable files from the worker directory
    file_contents = []
    for f in editable_files:
        fpath = worker_dir / f
        if fpath.exists():
            content = fpath.read_text()
            file_contents.append(f"### {f}\n\n{content}")
        else:
            file_contents.append(f"### {f}\n\n[FILE NOT FOUND]")

    all_content = "\n\n---\n\n".join(file_contents)

    # Build the judge prompt
    judge_prompt = f"""You are an expert evaluator. Score the following document against the rubric below.

## Target
{target}

## Rubric
{rubric}

## Document to evaluate

{all_content}

## Instructions

Score each criterion on the rubric from 1-10. Then compute the weighted sum as the final score.

You MUST respond with ONLY a valid JSON object in this exact format:
{{
  "scores": {{
    "criterion_name": {{"score": N, "reasoning": "one sentence"}},
    ...
  }},
  "final_score": N
}}

Where final_score = sum(score * weight) for each criterion. The maximum possible score is 100.

Respond with ONLY the JSON object. No other text."""

    # Call Claude
    model = os.environ.get("AUTORESEARCH_JUDGE_MODEL", "claude-sonnet-4-5-20250929")
    client = anthropic.Anthropic(api_key=api_key)

    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": judge_prompt}],
        )
        response_text = response.content[0].text.strip()

        # Parse JSON response
        # Handle potential markdown code blocks
        if response_text.startswith("```"):
            response_text = re.sub(r"^```\w*\n?", "", response_text)
            response_text = re.sub(r"\n?```$", "", response_text)

        result = json.loads(response_text)
        final_score = float(result["final_score"])

        # Write detailed scores to worker dir for the experiment log
        scores_path = worker_dir / "eval_scores.json"
        scores_path.write_text(json.dumps(result, indent=2))

        # Print the single number to stdout (this is what eval.sh captures)
        print(f"{final_score:.1f}")

    except json.JSONDecodeError as e:
        print(f"ERROR: Failed to parse judge response as JSON: {e}", file=sys.stderr)
        print(f"Response was: {response_text[:500]}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Judge evaluation failed: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
