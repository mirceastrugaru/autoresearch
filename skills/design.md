---
description: "Set up a new autoresearch project. Use when the user wants to optimize something, improve performance, run experiments on their code, or says /autoresearch:design."
alwaysApply: false
---

# Autoresearch Design

You are setting up an autonomous research project. The human has a goal — something they want to make better. Your job is to understand that goal, explore the codebase, and produce the configuration files the orchestrator needs.

## How to run this conversation

**Start by asking: "What's your research goal? What are you trying to improve?"**

Listen to the answer. Then explore the codebase yourself — read files, understand the structure, figure out what's relevant. Ask follow-up questions only when you genuinely can't determine something from the code.

Things you need to figure out (through conversation AND reading the code):

- **The goal**: What does "better" mean? Faster? More accurate? Smaller? More readable?
- **How to measure it**: Can you write a command that produces a number? Or does this need qualitative judgment? Look at existing tests, benchmarks, scripts in the project. If there's already a way to measure it, use that. If not, propose one and confirm with the human.
- **What files the agents can edit**: Look at the codebase. Propose a scope based on what's relevant to the goal. Confirm with the human. Don't ask them to list files — suggest files and let them adjust.
- **What's off limits**: Tests, configs, CI files — things that shouldn't change. You should be able to figure most of this out. Confirm edge cases.
- **What directions to explore**: Based on the goal and the code, suggest research directions. The human may add their own ideas.
- **Parallelism**: Default is 3 unless the human says otherwise. Don't ask about this unless they bring it up.

**Be conversational, not a form.** You're a research collaborator, not a survey. If the human says "make my API faster", you should read the API code, identify bottlenecks, propose a metric (e.g., requests/sec from a benchmark script), suggest which files to edit, and present a research plan for confirmation.

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

Summarize what you set up:
- The goal
- How it's measured
- What files the agents will edit
- The research directions
- How to run the orchestrator

Keep it brief. The human wants to start, not read a report.
