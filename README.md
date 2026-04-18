# Autoresearch

Autonomous experimentation for any codebase or research task. Point it at something you want to improve, define how to measure "better," and it runs parallel experiments — keeping what works, discarding what doesn't.

### How it works

- **You define a program** — a target (what to investigate), editable files, directions to prove and disprove, and a scoring rubric
- **Each round**, the orchestrator spawns N parallel Claude instances (workers) via the Agent SDK — half pro (arguing for the thesis), half con (arguing against)
- **Workers produce write-ups** with evidence for or against their assigned direction, scored by an LLM judge against a rubric with hard gates (factual correctness, evidence quality) and soft gates (domain-specific qualities you define)
- **In qualitative collaborative mode**, the judge scores all write-ups, synthesizes pro and con evidence into the next main document, and curates the roadmap — all in one call. In competitive mode, the highest scorer wins
- **The loop repeats** for a configurable number of rounds, with convergence detection that pivots strategy when progress stalls
- **A web monitor** serves a real-time dashboard (SSE) showing worker status, hypotheses, experiment log, and the evolving best document
- Everything runs headless through Claude Code — no API keys needed

Works on code (quantitative — eval script returns a number) and documents (qualitative — LLM judge scores against a rubric with hard/soft gates).

## When this fits

The tool is built around a pro/con loop: some workers try to support or improve the target, others try to disprove or break it. It fits whenever the question is **"is this true / is this right / will this work"**. It fits poorly when the question is **"just build this."**

**Strong fits**

- **Due diligence.** Bull case vs. bear case on a company, market, or investment thesis. Con-workers surface risks the pro-side glossed over. Output includes a list of attempted attacks and whether the thesis survived them.
- **Product rebuilds from source.** Pro-workers document architecture and intent; con-workers hunt for undocumented behavior, implicit coupling, and accumulated edge cases the rebuild would miss. The con-log is the landmine catalog.
- **Architecture decisions (ADRs).** Pro-workers build the case for each option, con-workers attack each. Output: a decision with counter-arguments already addressed. Better than a human writing an ADR alone — humans rarely steelman the option they've already dismissed.
- **Security review / threat modeling.** Literal red team / blue team. Pro argues the design is secure, con attacks it. Con-workers have unlimited productive attack surface.
- **Large PR or design-doc review.** Pro identifies what works, con hunts bugs, edge cases, perf regressions, API misuse. Scales past human reviewer fatigue.
- **Migration planning.** Pro catalogs what maps cleanly to the new system, con finds what breaks (transactions, query patterns, assumptions baked into the old schema).
- **Dependency / framework evaluation.** Pro reads docs and builds the case; con reads issues, changelogs, and post-mortems to build the anti-case.
- **Tech debt triage.** Pro argues each item is worth fixing; con argues it's not, or the fix makes things worse. Most tech-debt discussions are all-pro — this forces the other side.

**Decent fits**

- **Performance investigation** (usually better handled by quantitative mode with an eval script).
- **Test strategy / coverage audits.**
- **Complex incident post-mortems** where the obvious root cause isn't the real one.
- **API design**, when you want adversarial review more than user iteration.

**Weak fits — use a normal agent instead**

- **Writing new features from a spec.** No thesis to attack.
- **Bug fixing a known bug.** The fix is the answer.
- **Mechanical refactoring.**
- **Documenting existing code** (pro-only work; con-workers have nothing real to attack).

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

### Monitor

Watch runs in real-time in your browser:

```bash
python3 /path/to/autoresearch-skills/bin/monitor.py <project_dir> <initiative_name> --port 8082
```

Shows worker status, hypotheses, experiment log, and a viewer for the best document. Uses SSE for live updates — no page refresh needed.

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
2

## Editable files
- {file1}
- {file2}

## Directions to prove
- {direction supporting the thesis}
- {another direction}

## Directions to disprove
- {direction challenging the thesis}
- {another direction}
```

Two default combinations:
- **competitive + quantitative**: workers race on a number. Default for optimization problems.
- **collaborative + qualitative**: workers accumulate findings. Default for research and documents.

The orchestrator warns on unusual combinations (competitive + qualitative tends to plateau; collaborative + quantitative loses information when merging) but does not forbid them.

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
- `AUTORESEARCH_WORKER_TIMEOUT` — per-worker hard timeout in seconds (default: `900`)

## License

MIT
