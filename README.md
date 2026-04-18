# Autoresearch

Autonomous experimentation for any codebase or research question. Define a target, directions to investigate, and how to measure quality. The orchestrator spawns parallel Claude Code instances that iteratively build evidence — supportive workers collect evidence consistent with each direction, adversarial workers collect evidence inconsistent with it.

### How it works

- **You define a program** — a target, editable files, broad directions to investigate, and a scoring rubric
- **Each round**, the orchestrator spawns N parallel workers via the Claude Agent SDK — half supportive, half adversarial
- **Workers produce write-ups** with evidence for their assigned direction and stance, plus proposals for new directions to investigate
- **A judge** scores all write-ups against the rubric, synthesizes findings into the main document, and curates the roadmap of directions
- **The loop repeats** with convergence detection that pivots strategy when progress stalls
- **Direction discovery is exponential** — each worker proposes 3-4 new directions per round, the judge curates them, and the next round's workers investigate the best ones
- Everything runs headless through Claude Code — no API keys needed

Works on code (quantitative — eval script returns a number) and documents (qualitative — LLM judge scores against a rubric with hard/soft gates).

## When this fits

The tool is built around a supportive/adversarial loop: some workers collect evidence consistent with a direction, others collect evidence inconsistent. It fits whenever the question is **"is this true / is this right / will this work"**. It fits poorly when the question is **"just build this."**

**Strong fits**

- **Due diligence.** Bull case vs. bear case on a company or investment thesis. Adversarial workers surface risks the supportive side glossed over.
- **Product rebuilds from source.** Supportive workers document architecture and intent; adversarial workers hunt for undocumented behavior and edge cases the rebuild would miss.
- **Architecture decisions (ADRs).** Supportive workers build the case for each option, adversarial workers attack each. Output: a decision with counter-arguments already addressed.
- **Security review / threat modeling.** Literal red team / blue team. Supportive argues the design is secure, adversarial attacks it.
- **Migration planning.** Supportive catalogs what maps cleanly to the new system, adversarial finds what breaks.
- **Dependency / framework evaluation.** Supportive reads docs and builds the case; adversarial reads issues, changelogs, and post-mortems.

**Weak fits — use a normal agent instead**

- Writing new features from a spec
- Bug fixing a known bug
- Mechanical refactoring

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

The skill asks your goal, researches the domain, presents directions, writes config files, and runs the orchestrator loop.

```
/autoresearch:review
```

Review past results: what improved, what failed, convergence events.

### Manual

```bash
python3.13 /path/to/autoresearch-skills/bin/orchestrator.py 10 . <initiative-name>
python3.13 /path/to/autoresearch-skills/bin/orchestrator.py --help
python3.13 /path/to/autoresearch-skills/bin/orchestrator.py 10 . my-initiative --workers 4 --max-cost 5.00
```

## Configuration

Each initiative lives in `autoresearch/<name>/` with:

### program.md

```markdown
# Research Program

## Target
{what you're investigating}

## Metric
{what "better" means}

## Strategy
collaborative

## Measurement
qualitative

## Direction
maximize

## Parallelism
2

## Editable files
- {file1}

## Directions
- {broad direction 1}
- {broad direction 2}
- {broad direction 3}

## Rubric

Hard gates (fail any = score 0):
- correctness: no factual errors — every specific claim backed by a named, verifiable source
- evidence: every non-trivial claim has a specific, named, non-marketing source

Soft gates (each pass = +1 point):
- technical_specificity: concrete details (numbers, versions, measurements), not generalizations
- analytical_reasoning: connects facts into arguments with stated conclusions
- causal_implications: traces cause -> effect -> consequence with evidence
- investigative_effort: evidence of real digging, not just summarizing docs
{add domain-specific soft gates}

Score: 0 (hard gate fail) or 0-N (soft gate count).
```

Two default combinations:
- **collaborative + qualitative**: workers accumulate findings, judge synthesizes. Default for research and documents.
- **competitive + quantitative**: workers race on a number. Default for optimization.

### eval.sh

Quantitative: bash script, takes directory arg, prints one number. Qualitative: calls `eval_qualitative.py` which sends the document + rubric to an LLM judge.

### lockfile.txt

Files workers must not edit, one per line.

## Convergence

- 3 rounds without improvement: warns workers to diversify
- 5 rounds: forces strategy pivot (new branch from baseline)
- 8+ experiments with no best score change: forces pivot
- Every 10 experiments: re-validates best score

## Environment variables

- `AUTORESEARCH_MODEL` — worker model (default: `claude-haiku-4-5-20251001`)
- `AUTORESEARCH_JUDGE_MODEL` — qualitative judge model (default: `claude-sonnet-4-6`)
- `AUTORESEARCH_WORKER_TIMEOUT` — per-worker hard timeout in seconds (default: `900`)
- `AUTORESEARCH_MERGE_TIMEOUT` — merge agent timeout in seconds (default: `300`)

## License

MIT
