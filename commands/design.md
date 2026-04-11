---
description: "Set up a new autoresearch project. Interviews you about what to optimize, how to measure it, and what the agent can edit. Creates the config files so you can run the orchestrator."
alwaysApply: false
---

# Autoresearch Design

You are setting up a new autoresearch project. Interview the human to collect the information needed, then write the configuration files.

## Questions

Ask these one at a time. Wait for each answer before proceeding.

1. "What file or directory do you want to optimize?"
2. "What does 'better' mean? Describe the metric you care about."
3. "Is your metric quantitative (a command outputs a number) or qualitative (requires judgment against criteria)?"
4. **If quantitative:** "Provide a shell command that outputs a single number to stdout. This becomes eval.sh. The command will receive a directory path as its first argument — the files to evaluate will be in that directory."
   **If qualitative:** "Define 3-5 evaluation criteria. For each, give a name, description, weight (weights must sum to 1.0), and scoring scale (e.g., 1-10)."
5. "Which files can the agent edit? Which files are off limits?"
6. "What directions should the agent explore? List ideas, strategies, or constraints."
7. "How many experiments should run in parallel per round? (default: 3)"

## After collecting answers

Create the `autoresearch/` directory in the current working directory, then write these files:

### autoresearch/program.md

```markdown
# Research Program

## Target
{answer to question 1}

## Metric
{answer to question 2}

## Mode
{quantitative or qualitative}

## Parallelism
{answer to question 7, or 3 if default}

## Editable files
- {file1}
- {file2}

## Directions to explore
{answer to question 6}
```

If qualitative, also add:

```markdown
## Rubric
| Criterion | Weight | Scale | Description |
|-----------|--------|-------|-------------|
| {name}    | {weight} | 1-10 | {description} |
```

### autoresearch/eval.sh

**If quantitative:** Write the scoring command as an executable bash script:
- Start with `#!/bin/bash`
- Accept a directory argument: `EVAL_DIR="${1:-.}"`
- Run the scoring command using files from `$EVAL_DIR`
- Output exactly one number to stdout
- `chmod +x` it

**If qualitative:** Write a placeholder:
```bash
#!/bin/bash
echo "ERROR: qualitative mode — orchestrator uses subagent evaluation" >&2
exit 1
```

### autoresearch/lockfile.txt

The files the agent must NOT edit, one per line. Empty file if none.

## After writing files

Print:
```
Design complete. Files written:
  autoresearch/program.md
  autoresearch/eval.sh
  autoresearch/lockfile.txt

To run experiments:
  python3 /path/to/autoresearch-skills/bin/orchestrator.py <rounds> .
```

Replace `/path/to/` with the actual path to the autoresearch-skills directory if you can determine it.
