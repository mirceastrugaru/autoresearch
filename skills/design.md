---
description: "Set up a new autoresearch project. Use when the user wants to optimize something, improve performance, run experiments on their code, research a topic iteratively, or says /autoresearch:design."
alwaysApply: false
---

# Autoresearch Design

You are setting up an autonomous research project. The human has a goal — something they want to make better. Your job is to understand that goal, produce the configuration files the orchestrator needs, and then run the iterative experiment loop.

## MANDATORY: You MUST follow Phases 1-4 in order. Do NOT skip phases. Do NOT "just do it yourself."

The entire point of autoresearch is the iterative loop — multiple rounds of parallel agents, each improving on the last. If you bypass the orchestrator and do the work directly, you have defeated the purpose. This applies to ALL goals: code optimization, document writing, research, analysis, prompt engineering — everything.

## What kind of project is this?

Two orthogonal decisions:

**Strategy** — how do workers relate to each other?
- `competitive`: one best answer exists, workers race to find it. Best score wins, rest discarded. Use for optimization problems: faster code, better accuracy, smaller binary.
- `collaborative`: workers explore independent dimensions, all valid work accumulates. Every worker that passes hard gates gets merged into the baseline. Use for research, analysis, documents.

**Measurement** — how is quality measured?
- `quantitative`: eval script runs the output and returns a number. Use when quality can be measured automatically (benchmarks, tests, metrics).
- `qualitative`: LLM judge scores against a rubric. Use when quality requires judgment (documents, research, design).

Determine both for the human's goal before proceeding.

## Phase 1: Understand the goal

**Start by asking: "What's your research goal? What are you trying to improve?"**

Listen to the answer. Then figure out the project type:

**If the goal involves code**: Read the codebase — understand the structure, find what's relevant, look for existing tests and benchmarks. Figure out as much as you can before saying anything else.

**If the goal involves research/documents**: Determine what the output document should contain, what "better" means for it, and what sources/approaches the agents should use.

After your analysis, present a **complete research plan** in one message:

- A short name for this initiative (slug format, e.g. `sort-optimization`, `api-latency`)
- Here's what I think we're optimizing
- Strategy: competitive or collaborative — and why
- Measurement: quantitative or qualitative — and why
- Here's how I'll measure it (eval script for code / rubric criteria for documents)
- Here are the files the agents will edit
- Here are the files that are off-limits
- Here are the research directions I'd explore
- Recommended: N workers, M rounds, estimated cost ~$X
- Does this look right? Anything you'd change?

**ONE follow-up, not a questionnaire.** The human confirms or adjusts, then you write the config files. That's it — two exchanges maximum.

Things you figure out yourself (do NOT ask the human):

- **The initiative name**: derive from the goal. Keep it short, lowercase, hyphenated.
- **What files to edit**: For code — look at imports, call graphs. For documents — create the initial document.
- **What's off limits**: Tests, configs, CI, build files, lockfiles, eval infrastructure.
- **How to measure it**: For code — existing benchmarks or write an eval script. For documents — design a rubric with weighted criteria.
- **Research directions**: Specific, actionable ideas for improvement.
- **Parallelism and rounds**: Recommend based on problem complexity and expected cost. Simple optimization: 3 workers, 5 rounds. Deep research: 3 workers, 10 rounds. Present estimate to human — they confirm or adjust.

**Only ask the human when you genuinely cannot determine something from the code or context.**

## Phase 2: Write the config files

Each initiative gets its own directory under `autoresearch/`. Create `autoresearch/<name>/` with:

### autoresearch/<name>/program.md

```markdown
# Research Program

## Target
{what we're optimizing, in plain language}

## Metric
{what "better" means and how we measure it}

## Strategy
{competitive or collaborative}

## Measurement
{quantitative or qualitative}

## Direction
{maximize or minimize — e.g., minimize for latency/time, maximize for throughput/accuracy/quality}

## Parallelism
{default 3}

## Editable files
- {file1}
- {file2}

## Directions to explore
{research directions — specific, actionable ideas}
```

**For qualitative measurement, add a `## Rubric` section with hard and soft gates:**

```markdown
## Rubric

Hard gates (fail any = score 0):
- correctness: no factual errors — every specific claim backed by a named, plausible, verifiable source
- evidence: every non-trivial claim has a specific, named, non-marketing source

Soft gates (each pass = +1 point):
- technical_specificity: concrete details (numbers, versions, measurements), not generalizations
- analytical_reasoning: connects facts into arguments with stated conclusions
- causal_implications: traces cause → effect → consequence with evidence
- investigative_effort: evidence of real digging (source code, commits, APIs, configs) not just summarizing docs pages
{add domain-specific soft gates here based on the initiative's goal}

Score: 0 (hard gate fail) or 0-N (soft gate count).
```

The four universal soft gates (technical_specificity, analytical_reasoning, causal_implications, investigative_effort) must always be present. Add domain-specific gates on top using judgment — for example: comparative_insight when comparing options, trend_analysis when temporal change matters. Do not use a fixed list; pick what fits the specific goal.

The hard/soft structure and gate names must be preserved as-is — the eval script depends on parsing them.

### autoresearch/<name>/eval.sh

**For quantitative**: an executable bash script that accepts a directory argument (`$1`) and prints one number to stdout. Build from existing benchmarks if possible. Make it executable.

**For qualitative**: a bash script that calls the LLM-as-judge evaluator. Use this template:

```bash
#!/usr/bin/env bash
set -euo pipefail
WORKER_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
/opt/homebrew/bin/python3.13 "$SCRIPT_DIR/../../bin/eval_qualitative.py" "$WORKER_DIR" "$SCRIPT_DIR"
```

Make it executable. The `eval_qualitative.py` script reads the rubric from program.md, reads the editable files from the worker directory, and uses an LLM to score them.

### autoresearch/<name>/lockfile.txt

Files the agents must not edit, one per line.

### For qualitative/document projects: Create the initial document

If the editable file is a document (e.g. `analysis.md`), write an initial version with a solid structure and seed content. This becomes the baseline that agents will iteratively improve. Don't leave it empty — give the agents something substantive to work with so the first round of experiments can focus on improving specific sections rather than writing from scratch.

Place this file in the project directory at the path listed in "Editable files".

## Phase 3: Run the experiments

After writing the files, ask: **"Ready to start? How many rounds? (default: 10, that's 30 experiments)"**

When they confirm, find the orchestrator script. Search for it:
1. Common locations: `~/Desktop/Projects/autoresearch-skills/bin/orchestrator.py`
2. Search: `find ~ -path "*/autoresearch-skills/bin/orchestrator.py" -maxdepth 4 2>/dev/null | head -1`

If `ANTHROPIC_API_KEY` is not in the environment, ask the human for it before running.

Run it directly using the Bash tool (NOT in background — you need to see the output):

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY /opt/homebrew/bin/python3.13 <orchestrator_path> <rounds> . <name>
```

Set the Bash timeout to 600000 (10 minutes).

While it runs, the output streams back to you. After each round, relay the key info to the human:
- Which round finished, what scores workers got
- Which worker was promoted or if no improvement
- Current best score

## Phase 4: Present results

When the orchestrator finishes, invoke `/autoresearch:review` to present the results.

## CRITICAL REMINDERS

- **NEVER skip the orchestrator.** Do not do the work yourself. Do not spawn your own agents outside the orchestrator. The orchestrator IS the product.
- **NEVER skip Phase 2.** You must write program.md, eval.sh, and lockfile.txt before running.
- **NEVER skip Phase 3.** The iterative loop must run. One-shot answers defeat the purpose.
- **Qualitative mode is real.** Research, analysis, documents — all go through the loop. The LLM judge scores them. Multiple rounds improve them. This is not just for code.
