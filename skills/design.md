---
description: "Set up a new autoresearch project. Use when the user wants to optimize something, improve performance, run experiments on their code, or says /autoresearch:design."
alwaysApply: false
---

# Autoresearch Design

You are setting up an autonomous research project. The human has a goal — something they want to make better. Your job is to understand that goal, explore the codebase, and produce the configuration files the orchestrator needs. Then run the experiments and present results.

## Phase 1: Understand the goal

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

Things you figure out BY READING THE CODE (do NOT ask the human):

- **What files to edit**: Look at imports, call graphs, the directory structure.
- **What's off limits**: Tests, configs, CI, build files, lockfiles. Obvious from the project structure.
- **How to measure it**: Look for existing benchmarks, test scripts, Makefiles. If none exist, write an eval script yourself.
- **Research directions**: Read the code and identify concrete opportunities.
- **Parallelism**: Default 3. Never ask about this.

**Only ask the human when you genuinely cannot determine something from the code.**

## Phase 2: Write the config files

Create `autoresearch/` in the current working directory with:

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

If qualitative, add a `## Rubric` section with criteria, weights, and scale.

### autoresearch/eval.sh

For quantitative: an executable bash script that accepts a directory argument (`$1`) and prints one number to stdout. Build from existing benchmarks if possible. Make it executable.

For qualitative: a placeholder that errors (the orchestrator handles qualitative eval differently).

### autoresearch/lockfile.txt

Files the agents must not edit, one per line.

## Phase 3: Run the experiments

After writing the files, ask: **"Ready to start? How many rounds? (default: 10, that's 30 experiments)"**

When they confirm, find the orchestrator script. Search for it:
1. Check if `autoresearch` plugin is installed: look for `bin/orchestrator.py` relative to the plugin install path
2. Common locations: `~/Desktop/Projects/autoresearch/bin/orchestrator.py`, `~/autoresearch/bin/orchestrator.py`
3. Search: `find ~ -path "*/autoresearch/bin/orchestrator.py" -maxdepth 4 2>/dev/null | head -1`

If `ANTHROPIC_API_KEY` is not in the environment, ask the human for it before running.

Run it directly using the Bash tool (NOT in background — you need to see the output):

```bash
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY python3.13 <orchestrator_path> <rounds> .
```

Set the Bash timeout to 600000 (10 minutes).

While it runs, the output streams back to you. After each round, relay the key info to the human:
- Which round finished, what scores workers got
- Which worker was promoted or if no improvement
- Current best score

## Phase 4: Present results

When the orchestrator finishes, invoke `/autoresearch:review` to present the results.
