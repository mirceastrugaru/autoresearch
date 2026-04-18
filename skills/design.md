---
description: "Set up a new autoresearch project. Use when the user wants to optimize something, improve performance, run experiments on their code, or says /autoresearch:design."
alwaysApply: false
---

# Autoresearch Design

You are setting up an autonomous research project. The human has a goal — something they want to make better. Your job is to understand that goal, explore the codebase, and produce the configuration files the orchestrator needs.

## How to run this conversation

**Start by asking: "What's your research goal? What are you trying to improve?"**

Listen to the answer. Then **shut up and read the code.** Explore the codebase — understand the structure, find what's relevant, look for existing tests and benchmarks. Figure out as much as you can before saying anything else.

After reading the code, present a **complete research plan** in one message:

- Here's what I think we're optimizing
- Here's how I'll measure it (found this benchmark / I'll write this eval script)
- Here are the files the agents will edit
- Here are the files that are off-limits
- Here are the research directions I'd explore
- Does this look right? Anything you'd change?

**ONE follow-up, not a questionnaire.** The human confirms or adjusts, then you write the config files. That's it — two exchanges maximum.

Things you need to figure out BY READING THE CODE (do NOT ask the human):

- **What files to edit**: Look at imports, call graphs, the directory structure. If the goal is "make the sort faster", find the sort code.
- **What's off limits**: Tests, configs, CI, build files, lockfiles. Obvious from the project structure.
- **How to measure it**: Look for existing benchmarks, test scripts, Makefiles. If none exist, write an eval script yourself based on what the code does.
- **Research directions**: Read the code and identify concrete opportunities. Don't ask the human "what directions?" — propose directions based on what you see.
- **Parallelism**: Default 3. Never ask about this.

**Only ask the human when you genuinely cannot determine something from the code.** For example, if there are multiple plausible metrics and you can't tell which one matters more.

## When you have enough information

Write three files:

### autoresearch/program.md

```markdown
# Research Program

## Target
{what we're optimizing, in plain language}

## Metric
{what "better" means and how we measure it}

## Mode
{quantitative or qualitative}

## Parallelism
{default 3}

## Editable files
- {file1}
- {file2}

## Directions to explore
{research directions — specific, actionable ideas}
```

If qualitative, add a rubric:
```markdown
## Rubric
| Criterion | Weight | Scale | Description |
|-----------|--------|-------|-------------|
| ...       | ...    | 1-10  | ...         |
```

### autoresearch/eval.sh

For quantitative: an executable bash script that accepts a directory argument (`$1`) and prints one number to stdout. Build this from existing benchmarks/tests if possible, or write a new one.

For qualitative: a placeholder that errors (the orchestrator handles qualitative eval differently).

Make it executable.

### autoresearch/lockfile.txt

Files the agents must not edit, one per line.

## After writing files

Briefly summarize what you set up (goal, metric, files, directions). Then ask:

**"Ready to start? How many rounds? (default: 10, that's 30 experiments)"**

When they confirm, run the orchestrator directly using the Bash tool (NOT in background — you want to see the output):

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY python3.13 /Users/mircea/Desktop/Projects/autoresearch/bin/orchestrator.py <rounds> .
```

Set the timeout to 600000 (10 minutes) since this takes a while.

If `ANTHROPIC_API_KEY` is not in the environment, ask the human for it before running. Do not tell them to run it themselves — you run it.

While it runs, the output streams back to you. After each round completes, relay the key info to the human:
- Which round just finished
- What scores the workers got
- Which worker was promoted (or if no improvement)
- Current best score

When the orchestrator finishes, immediately present the results — read `autoresearch/log.jsonl` and `autoresearch/best_score.txt` and show:
- Starting score vs final score
- Total improvement
- List of kept experiments with hypotheses
- The best code is in `autoresearch/best/`

Do NOT tell them to run `/autoresearch:review`. You ARE the review. Show them the results right here.
