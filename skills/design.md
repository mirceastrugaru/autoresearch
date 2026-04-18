---
description: "Set up a new autoresearch project. Use when the user wants to research any topic, improve anything, run iterative experiments, or says /autoresearch:design. Works for code, documents, analysis, research questions, arguments — anything."
alwaysApply: false
---

# Autoresearch Design

You are setting up an autonomous research project. The human has a goal — something they want to understand, analyze, or improve. Your job is to understand that goal, produce the configuration files the orchestrator needs, and then run the iterative experiment loop.

## MANDATORY: You MUST follow Phases 1-6 in order. Do NOT skip phases. Do NOT "just do it yourself."

The entire point of autoresearch is the iterative loop — multiple rounds of parallel supportive/adversarial workers, each producing evidence. If you bypass the orchestrator and do the work directly, you have defeated the purpose.

## What kind of project is this?

Two modes:

- **qualitative**: workers produce write-ups (evidence consistent/inconsistent with directions), an LLM judge scores and synthesizes into a main document. Default for research, analysis, documents, DD, decisions, evaluations.
- **quantitative**: workers edit code, eval script returns a number, best score wins. Default for optimization (faster code, better accuracy, lower latency).

Determine which fits the user's goal before proceeding.

## Phase 1: Understand the goal

Start with the goal. If the user's request is clear, proceed directly. If ambiguous, ask one concise clarifying question — not a checklist.

Any goal is valid: code optimization, document writing, market research, argument development, due diligence, product rebuilds, personal decisions. Do not redirect the user based on goal type.

**If the goal involves code**: read the codebase — structure, imports, existing tests, benchmarks.

**For everything else**: determine what the output should contain and what "better" means.

## Phase 2: Propose a research plan

Before you can propose directions, you need to understand the domain. Propose a short research plan — what you'll investigate before drafting the agenda:

```
Before I propose directions, I'd research:
- [specific thing to investigate 1]
- [specific thing to investigate 2]
- [specific thing to investigate 3]

Add anything? Remove anything? Reply with edits or "go."
```

Wait for confirmation. The user may add, remove, or just say go.

## Phase 3: Do the research

Execute the research plan. For code goals: read the target files, imports, call graphs. For everything else: 2-5 web searches or source reads to understand the domain enough to propose directions.

Keep it bounded — 5 minutes of work max. This is setup, not execution. The loop does the deep work.

## Phase 4: Propose the agenda

Present a list of broad initial directions to investigate. Do NOT pre-decompose into specific sub-vectors — the workers will discover specific angles during research and propose them via the roadmap.

Derive directions from the goal itself. If the goal is a thesis with claims, each claim is a direction. If the goal is analysis, each major area of concern is a direction. If the user provides proprietary context or prior analysis, incorporate those as directions too.

```
**<name>** — <one-line goal>

Directions:
- <broad direction 1>
- <broad direction 2>
- <broad direction 3>
- <broad direction 4>

<N> workers (N/2 supportive + N/2 adversarial), <M> rounds, ~$<X>. Ready?
```

Aim for 3-6 broad directions. Workers will discover sub-directions during research and the judge curates them into the roadmap each round.

Wait for the human to edit and confirm. They may strike, add, or rearrange.

Things you figure out yourself (do NOT ask the human):

- **The initiative name**: derive from the goal. Short, lowercase, hyphenated.
- **Measurement mode**: determine from the goal type.
- **What files to edit**: for code — look at imports, call graphs. For documents — create the initial document.
- **What's off limits**: tests, configs, CI, build files, eval infrastructure.
- **How to measure it**: for code — existing benchmarks or write an eval script. For documents — design a rubric.
- **Parallelism**: default 2 (1 supportive + 1 adversarial). Must be even.
- **Rounds**: default 5.

## Phase 5: Write the config files

Each initiative gets its own directory under `autoresearch/`. Create `autoresearch/<name>/` with:

### autoresearch/<name>/program.md

```markdown
# Research Program

## Target
{what we're investigating, in plain language}

## Metric
{what "better" means and how we measure it}

## Strategy
collaborative

## Measurement
{quantitative or qualitative}

## Direction
maximize

## Parallelism
{default 2, must be even}

## Editable files
- {file1}
- {file2}

## Directions
- {broad direction 1}
- {broad direction 2}
- {broad direction 3}
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
- causal_implications: traces cause -> effect -> consequence with evidence
- investigative_effort: evidence of real digging (source code, commits, APIs, configs) not just summarizing docs pages
{add domain-specific soft gates here based on the initiative's goal}

Score: 0 (hard gate fail) or 0-N (soft gate count).
```

The four universal soft gates must always be present. Add domain-specific gates on top.

### autoresearch/<name>/eval.sh

**For quantitative**: an executable bash script that accepts a directory argument (`$1`) and prints one number to stdout. Make it executable.

**For qualitative**: a bash script that calls the LLM-as-judge evaluator:

```bash
#!/usr/bin/env bash
set -euo pipefail
WORKER_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
/opt/homebrew/bin/python3.13 "$SCRIPT_DIR/../../bin/eval_qualitative.py" "$WORKER_DIR" "$SCRIPT_DIR"
```

Make it executable.

### autoresearch/<name>/lockfile.txt

Files the workers must not edit, one per line.

### For qualitative/document projects: Create the initial document

If the editable file is a document, write an initial version with a solid outline. This becomes the baseline the judge iteratively improves. Don't leave it empty.

## Phase 6: Run the experiments

After writing the files, ask: **"Ready to start? How many rounds? (default: 5)"**

When they confirm, find the orchestrator script:
1. Common location: `~/Desktop/Projects/autoresearch-skills/bin/orchestrator.py`
2. Search: `find ~ -path "*/autoresearch-skills/bin/orchestrator.py" -maxdepth 4 2>/dev/null | head -1`

Run it directly using the Bash tool (NOT in background):

```bash
/opt/homebrew/bin/python3.13 <orchestrator_path> <rounds> . <name>
```

Set the Bash timeout to 600000 (10 minutes).

## Phase 7: Present results

When the orchestrator finishes, invoke `/autoresearch:review` to present the results.

## CRITICAL REMINDERS

- **NEVER skip the orchestrator.** Do not do the work yourself.
- **NEVER skip Phase 5.** You must write program.md, eval.sh, and lockfile.txt before running.
- **NEVER skip Phase 6.** The iterative loop must run.
- **Parallelism must be even.** Minimum 2 (1 supportive + 1 adversarial).
