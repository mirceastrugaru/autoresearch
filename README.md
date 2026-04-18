# Autoresearch

Autonomous experimentation for any codebase. Point it at code you want to optimize, give it a metric, and it runs parallel experiments — keeping what works, discarding what doesn't.

Inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) and [ResearcherSkill](https://github.com/krzysztofdudek/ResearcherSkill), generalized beyond ML to anything you can measure.

## What it does

You have code. Something about it could be better — faster, smaller, more accurate. You can measure "better" with a command that prints a number.

Autoresearch spawns parallel AI agents that each try a different change, measure the result, and compete. The best improvement wins and becomes the new baseline. Losers get thrown away. Repeat.

```
Round 1:  worker-1: 4.8M   worker-2: 5.1M ★  worker-3: 4.6M    → promote worker-2
Round 2:  worker-1: 9.9M   worker-2: 12.3M ★ worker-3: 9.6M    → promote worker-2
Round 3:  worker-1: 12.4M ★ worker-2: 12.3M  worker-3: 10.5M   → promote worker-1
```

After 30 rounds you come back to code that's measurably better, a log of every experiment that was tried, and a summary of what worked.

## Install

```bash
git clone https://github.com/mirceastrugaru/autoresearch.git
cd autoresearch
./install.sh
```

The install script:
- Registers the plugin in Claude Code (permanent — survives restarts)
- Checks for Python 3.10+ and installs `claude-agent-sdk` if needed
- Tells you if `ANTHROPIC_API_KEY` is missing and where to get one

After install, restart Claude Code. The `/autoresearch:design` and `/autoresearch:review` commands will be available in every session.

## Usage

### 1. Design (interactive)

In any Claude Code session with the plugin loaded:

```
/autoresearch:design
```

This interviews you:
- What do you want to optimize?
- How do you measure it?
- Which files can the agent edit?
- What directions should it explore?

It writes three files in your project:
- `autoresearch/program.md` — the research program
- `autoresearch/eval.sh` — the scoring command
- `autoresearch/lockfile.txt` — files the agent must not touch

### 2. Run (from terminal)

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
python3 /path/to/autoresearch-skills/bin/orchestrator.py <rounds> <project-dir>
```

For example, 10 rounds on the current directory:

```bash
python3 /path/to/autoresearch-skills/bin/orchestrator.py 10 .
```

Each round spawns N parallel agents (default 3). So 10 rounds = 30 experiments.

The orchestrator:
- Initializes directories and runs a baseline score
- Runs parallel experiments each round
- Promotes the best improvement, reverts the rest
- Detects convergence (discard streaks, plateaus) and pivots strategy
- Periodically writes a summary to `autoresearch/findings.md`
- Persists state — if it crashes or you stop it, re-run the same command to resume

### 3. Review (interactive)

Back in Claude Code:

```
/autoresearch:review
```

Shows you what happened: how many experiments, what improved, what failed, convergence events. You can drill into any specific experiment.

## How it works

### Architecture

```
You ←→ Claude Code          Terminal
         │                     │
    /design  /review      orchestrator.py
                               │
                    ┌──────────┼──────────┐
                    │          │          │
                worker-1   worker-2   worker-3
                (Agent SDK) (Agent SDK) (Agent SDK)
                    │          │          │
                 edit code  edit code  edit code
                 run eval   run eval   run eval
                    │          │          │
                    └──────────┼──────────┘
                               │
                         best wins →  new baseline
                         rest reverted
```

The slash commands run inside your Claude Code session — they're just instructions. The orchestrator is a Python script that uses the [Claude Agent SDK](https://pypi.org/project/claude-agent-sdk/) to spawn parallel agents. Each agent has full Claude Code capabilities: file access, bash, web search, MCP servers — whatever your Claude Code can do.

### The ratchet

Every round:
1. Copy current best code to N isolated worker directories
2. Each worker independently tries a change and measures the score
3. Mechanical checks: lockfile violations, safety violations, noise threshold
4. Best approved improvement gets promoted to the new baseline
5. Everything else gets thrown away

The score can only go up. Failed experiments are logged but never kept.

### Convergence

The orchestrator tracks discard streaks and plateaus:
- **3 consecutive rounds without improvement**: warns the agents to try something different
- **5 consecutive rounds**: forces a strategy pivot — creates a new branch from baseline
- **8+ experiments without best score changing**: forces a pivot
- **Every 10 experiments**: re-validates the best score to detect drift

### Branching

When forced to pivot, the orchestrator creates a new branch (a separate folder) forked from baseline. This escapes local optima — instead of tweaking the same approach, it starts fresh and tries something fundamentally different.

### Thought experiments

Agents can log reasoning without running code. If an agent determines an approach won't work through analysis alone, it writes a thought experiment instead of wasting a benchmark run.

## File structure

After running, your project will have:

```
your-project/
  autoresearch/
    program.md          ← research config (what to optimize, how)
    eval.sh             ← scoring command
    lockfile.txt        ← protected files
    state.json          ← orchestrator state (for resume)
    log.jsonl           ← every experiment, one JSON line each
    findings.md         ← auto-generated summary
    best_score.txt      ← current best score
    best/               ← the best version of your code
    branches/           ← strategy branches
      main/             ← initial strategy
      pivot-15/         ← divergent strategy (if pivoted)
    branches.jsonl      ← branch registry
```

## Configuration

### program.md

```markdown
# Research Program

## Target
code.py — sorting benchmark

## Metric
Throughput (higher is better)

## Mode
quantitative

## Parallelism
3

## Editable files
- code.py
- utils.py

## Directions to explore
- Replace bubble sort with faster algorithm
- Use numpy for array operations
- Minimize allocations
```

### Qualitative mode

If your metric isn't a number (e.g., "does this prompt produce better output?"), set Mode to `qualitative` and add a Rubric section:

```markdown
## Mode
qualitative

## Rubric
| Criterion | Weight | Scale | Description |
|-----------|--------|-------|-------------|
| Clarity   | 0.4    | 1-10  | How clear is the output? |
| Accuracy  | 0.4    | 1-10  | Are facts correct? |
| Brevity   | 0.2    | 1-10  | Is it concise? |
```

The orchestrator will use 3 independent AI evaluators per experiment, taking the median score.

### Environment variables

- `ANTHROPIC_API_KEY` — required for the orchestrator
- `AUTORESEARCH_MODEL` — override the model (default: `claude-sonnet-4-5-20250929`)

## License

MIT
