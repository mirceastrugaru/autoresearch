# Autoresearch

Autonomous experimentation for any codebase or research task. Point it at something you want to improve, define how to measure "better," and it runs parallel experiments — keeping what works, discarding what doesn't.

Works on code (quantitative — eval script returns a number) and documents (qualitative — LLM judge scores against a rubric with hard/soft gates).

## Install

```bash
git clone https://github.com/mirceastrugaru/autoresearch.git
cd autoresearch
./install.sh
```

Restart Claude Code after install. `/autoresearch:design` and `/autoresearch:review` will be available.

Requirements: Python 3.10+, `claude-agent-sdk`, Claude Code authenticated.

## Usage

```
/autoresearch:design
```

The skill asks your goal, reads your codebase, presents a plan, writes config files, and runs the orchestrator loop.

```
/autoresearch:review
```

Review past results: what improved, what failed, convergence events.

### Manual

```bash
python3.13 /path/to/autoresearch-skills/bin/orchestrator.py 10 . <initiative-name>
python3.13 /path/to/autoresearch-skills/bin/orchestrator.py --help
```

## Architecture

```
You ←→ Claude Code
         │
    /design  /review      orchestrator.py
                               │
                    ┌──────────┼──────────┐
                 worker-1   worker-2   worker-3
                 (Agent SDK) (Agent SDK) (Agent SDK)
                    │          │          │
                 edit + eval  edit + eval  edit + eval
                    └──────────┼──────────┘
                               │
                         best wins → new baseline
```

Each round: N parallel agents try different improvements, get scored, best gets promoted. Failed experiments logged and discarded. Convergence detection pivots strategy when stuck.

## Configuration

Each initiative lives in `autoresearch/<name>/` with:

### program.md

```markdown
# Research Program

## Target
{what you're improving}

## Metric
{what "better" means}

## Strategy
{competitive or collaborative}

## Measurement
{quantitative or qualitative}

## Direction
{maximize or minimize}

## Parallelism
3

## Editable files
- {file1}
- {file2}

## Directions to explore
{specific ideas to try}
```

**Strategy**: `competitive` — one winner per round, best score promoted, rest discarded. Use for optimization problems. `collaborative` — every worker that passes hard gates gets merged into the baseline. Use for research and documents.

**Measurement**: `quantitative` — eval script returns a number. `qualitative` — LLM judge scores against a rubric.

### Qualitative measurement

Set Measurement to `qualitative` and add a Rubric section:

```markdown
## Rubric

Hard gates (fail any = score 0):
- correctness: every claim backed by a named verifiable source
- evidence: every non-trivial claim has a specific non-marketing source

Soft gates (each pass = +1 point):
- technical_specificity: concrete details, not generalizations
- analytical_reasoning: facts connected into arguments with conclusions
- causal_implications: cause → effect → consequence traced
- investigative_effort: evidence of real digging, not summarizing docs
{add domain-specific gates as needed}

Score: 0 (hard gate fail) or 0-N (soft gate count).
```

The LLM judge (`bin/eval_qualitative.py`) reads the rubric and scores accordingly.

### eval.sh

Quantitative: bash script, takes directory arg, prints one number.

Qualitative: calls `eval_qualitative.py` which sends the document + rubric to an LLM judge.

### lockfile.txt

Files agents must not edit, one per line.

## Convergence

- 3 rounds without improvement: warns agents to diversify
- 5 rounds: forces strategy pivot (new branch from baseline)
- 8+ experiments with no best score change: forces pivot
- Every 10 experiments: re-validates best score

## Environment variables

- `AUTORESEARCH_MODEL` — model for experiment agents (default: `claude-sonnet-4-6`)
- `AUTORESEARCH_JUDGE_MODEL` — model for qualitative judge (default: `claude-sonnet-4-6`)

## License

MIT
