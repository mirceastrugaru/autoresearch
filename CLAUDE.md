# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Behavior

**Be adversarial, not agreeable.** If you disagree, say so immediately. Don't say "you're right, but..." — say what's wrong and why. The pushback is the valuable part.

**Follow skill instructions literally.** When a skill is invoked, execute its phases in order. Do not skip phases. Do not "just do it yourself." The orchestrator loop is the product.

**Autoresearch accepts any goal.** Do not reject or redirect goals because they are not software engineering tasks. Sleep habits, business questions, political analysis, personal decisions — all are valid autoresearch goals. Never tell the user to "consult a specialist" or suggest the tool isn't appropriate. Design the experiment and run it.

**Prompts are machine-readable.** Keep prompts compact. No filler, no pleasantries, no redundant explanation. Caveman language is fine if it's unambiguous.

## Quality standards

All output — code, documents, research — is held to these gates:

**Hard gates (fail = reject, no exceptions):**
- **Correctness**: no factual errors
- **Evidence**: non-trivial claims must have backing (citations, source references, data)

**Soft gates (fail = point deducted):**
- **Technical specificity**: concrete details, not generalizations
- **Comparative insight**: why a difference matters, not just that it exists
- **Analytical reasoning**: connect facts into arguments, derive conclusions
- **Causal implications**: trace cause → effect → consequence
- **Investigative effort**: evidence of digging — source code, commits, APIs, configs. Not just summarizing docs pages.

## What this repo is

A Claude Code plugin (`.claude-plugin/plugin.json`) that exposes two slash commands — `/autoresearch:design` and `/autoresearch:review` — plus a Python orchestrator that runs parallel Claude Agent SDK workers to iteratively improve code or documents. Everything runs headless through Claude Code; no API keys.

## Common commands

```bash
# Install plugin into Claude Code (adds marketplace + installs plugin user-scoped)
./install.sh

# Run orchestrator manually (from a project with autoresearch/<name>/ configured)
python3.13 bin/orchestrator.py <rounds> <project_dir> <initiative_name>
python3.13 bin/orchestrator.py --help
python3.13 bin/orchestrator.py 10 . my-initiative --workers 4 --max-cost 5.00

# Live dashboard over SSE (worker status, experiment log, best document viewer)
python3 bin/monitor.py <project_dir> <initiative_name> --port 8082

# Trace serialization tests
python3 bin/test_trace.py
```

No build, lint, or formal test suite beyond `test_trace.py`. Target Python is 3.10+ (installer prefers 3.13).

## Architecture

The system is a three-layer loop:

1. **Slash-command skills** (`skills/design.md`, `skills/review.md`) — mandatory multi-phase prompts that set up or debrief a run. `design.md` explicitly forbids bypassing the orchestrator; it must produce `program.md` / `eval.sh` / `lockfile.txt` and then invoke the orchestrator.

2. **Orchestrator** (`bin/orchestrator.py`, ~1700 lines, single async `main()` around line 848) — the heart of the system:
   - Discovers initiatives under `<project>/autoresearch/<name>/` (program.md presence = initiative).
   - Reads **strategy** (`competitive` | `collaborative`) and **measurement** (`quantitative` | `qualitative`) from `program.md`. Warns but doesn't block on unusual combinations.
   - Each round: spawns N parallel workers via `run_agent()` → `claude_agent_sdk.query` with `permission_mode="bypassPermissions"`. Shared context (`_build_shared_context`) goes into every worker's system prompt so all N workers get cache hits on the same bytes.
   - Workers have a **stance** (supportive or adversarial). Parallelism must be even (minimum 2): first half supportive, second half adversarial. Each worker is assigned a direction from `roadmap.md` via `parse_roadmap` + `assign_directions`, using a coverage matrix from `log.jsonl` to prioritize least-covered directions. Supportive workers collect evidence consistent with the direction; adversarial workers collect evidence inconsistent with it.
   - After workers finish: **quantitative** mode computes authoritative diffs from filesystem snapshots, runs `eval.sh`, promotes best (competitive) or merges via merge agent (collaborative). **Qualitative collaborative** mode collects all write-ups and calls the judge (`bin/eval_qualitative.py --judge`) which scores write-ups, synthesizes the next main document, and curates the roadmap — all in one call.
   - Convergence logic: `DISCARD_STREAK_WARN=3` adds guardrail message, `DISCARD_STREAK_PIVOT=5` forces `force_pivot` (new branch), `PLATEAU_THRESHOLD=8` unchanged-best-count forces pivot, `REVALIDATE_EVERY=10` re-runs eval on current best to detect noise.
   - Timeouts: `AUTORESEARCH_WORKER_TIMEOUT` (default 900s per worker), `AUTORESEARCH_MERGE_TIMEOUT` (300s). Hard-enforced via `asyncio.wait_for`.
   - Everything is traced: `message_to_trace_events` serializes every SDK message (AssistantMessage / UserMessage / ToolUseBlock / ToolResultBlock / ResultMessage) to per-experiment `traces/<exp_id>.jsonl` with bounded sizes (`TRACE_TOOL_RESULT_CAP=4000`, `TRACE_MESSAGE_HARD_CEILING=50000`). Traces survive crashes — line-buffered writes.

3. **Workers** — Claude Agent SDK instances following `prompts/supportive.md` (supportive stance) or `prompts/adversarial.md` (adversarial stance). Headless, one direction per invocation. Produce `hypothesis.txt`, `writeup.md`, `roadmap_append.md` (mandatory — drives direction discovery), `score.txt` (quantitative only), `summary.txt`, `status.txt`, and (last, mandatory) `experiment_id_output.txt`. Missing the final file = instruction-violation = discard.

## Initiative layout

Each initiative lives at `<project>/autoresearch/<name>/`:

- `program.md` — required. Parsed sections: `## Target`, `## Metric`, `## Strategy`, `## Measurement`, `## Direction`, `## Parallelism`, `## Editable files`, `## Directions`, and (qualitative only) `## Rubric`.
- `eval.sh` — required executable. Quantitative: prints one number. Qualitative: shells to `bin/eval_qualitative.py`.
- `lockfile.txt` — files workers must not edit. The orchestrator also auto-rejects writes to `eval.sh`, `program.md`, `state.json`, `log.jsonl`, `branches.jsonl`, `best_score.txt`, `lockfile.txt`.
- State produced by the loop: `state.json`, `log.jsonl` (every experiment), `branches.jsonl`, `best_score.txt`, `best/`, `branches/<branch>/`, `workers/worker-<i>/`, `traces/`, `prompts/<exp_id>.txt`, `findings.md`, `roadmap.md`.

## Rubric hard/soft structure is load-bearing

For qualitative initiatives, the parser in `bin/eval_qualitative.py` expects the exact structure in `program.md`:
- `Hard gates (fail any = score 0):` followed by `- gate_name: description` lines
- `Soft gates (each pass = +1 point):` with the same line shape

The LLM judge re-derives `final_score` from the per-gate pass/fail verdicts rather than trusting its own claim (see `eval_qualitative.py:144-157`) — any hard-gate fail zeroes the score regardless of soft gates.

## Environment variables

- `AUTORESEARCH_MODEL` — worker model (orchestrator default is `claude-haiku-4-5-20251001` per `bin/orchestrator.py:75`; README claims `claude-sonnet-4-6`; code is authoritative).
- `AUTORESEARCH_JUDGE_MODEL` — qualitative judge model (default `claude-sonnet-4-6`).
- `AUTORESEARCH_WORKER_TIMEOUT`, `AUTORESEARCH_MERGE_TIMEOUT` — seconds.
- `AUTORESEARCH_RUNAWAY_TURNS`, `AUTORESEARCH_LOG_BLOAT_BYTES` — tuning knobs for worker-runaway detection and log-size warnings.

## Invariants worth knowing before editing

- The orchestrator is **resumable**: if `state.json` exists it picks up from `state["round"]` without re-initializing. Don't break that by assuming cold start.
- `prepare_workers` rmtree's worker directories each round. Anything worth keeping must go under `ar_dir/` (e.g. `ar_dir/traces/`, `ar_dir/prompts/`), not under `workers/`.
- Workers communicate **only** via files in their worker dir. The orchestrator is the single writer of state/log/branches.
- Diff computation is filesystem-authoritative — never trust a worker's self-reported diff. See `snapshot_files` + `compute_diff`.
- Browser automation in this repo (when needed): prefer the globally installed `agent-browser` CLI over claude-in-chrome for headless tasks.
