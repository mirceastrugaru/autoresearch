# experiment

Headless worker. One invocation = one experiment. All context is pre-loaded in your system prompt. Your worker dir and task metadata are in the user prompt.

## Context you already have

System prompt: program.md, findings.md, full log, parking_lot.md, current best document.
User prompt: experiment ID, worker dir, eval command, branch, best score, parent experiment, role bias, time budget, optional parking-lot seed, optional guardrail warning.

Do NOT re-read any of these from disk. Read `branches.jsonl` only if you need deeper branch history.

## Procedure

1. **Decide hypothesis.** Inspect the log (what's been tried), findings.md, parking_lot.md. Do not repeat a logged experiment. One idea only. Your role bias (CONSERVATIVE/MODERATE/AGGRESSIVE) should shape the risk level of your hypothesis.

2. **Optional thought experiment.** If the question is conclusive from existing evidence alone (no new test needed), write `thought` to `status.txt`, your reasoning to `hypothesis.txt`, `0` to `score.txt`, then skip to step 6. Use sparingly — producing a real tested result is preferred.

3. **Write `hypothesis.txt`.** One sentence stating what you're trying and why.

4. **Edit editable files.** They are listed in program.md at project-relative paths (e.g. `autoresearch/foo/bar.md`) and live at that same relative path inside your worker dir. Edit only those. The orchestrator computes diffs from the filesystem — if you create files outside the editable set, touch forbidden files (eval.sh, program.md, state.json, log.jsonl, branches.jsonl, best_score.txt, lockfile.txt), or touch lockfile-listed paths, your work is automatically rejected. No self-reported diff needed.

5. **Run eval.** Execute the eval command from the user prompt. Write the resulting number to `score.txt`. Write `real` to `status.txt`. If eval fails or output isn't numeric: write `0` to `score.txt` and explain in `summary.txt`.

6. **Write `summary.txt`.** One paragraph: what you changed, what the result showed, what was surprising. This is the record future workers learn from. Be concrete.

7. **Write deferred ideas** to `parking_lot_<worker_number>.txt` (one per line). If a parking_lot idea was relevant to your experiment, note what you found. This file is merged back into the shared parking_lot by the orchestrator.

8. **LAST.** Write your experiment ID (from the user prompt) to `experiment_id_output.txt`. Nothing else after this — if this file is missing, your work is discarded.

Finish with: `EXPERIMENT COMPLETE. Score: {score}` or `THOUGHT EXPERIMENT COMPLETE.`

## Scoring

Quantitative mode: score is the number your eval produced. Competitive runs promote the best; collaborative runs merge everyone above a threshold.

Qualitative mode: an LLM judge scores against the rubric in program.md. Hard gates are pass/fail — any failure → score 0 regardless of soft gates. Soft gates increment score. The judge verifies claims. Work the rubric intentionally: every claim needs a source, concrete specifics beat generalities, dig into primary sources (code, commits, configs) rather than summarizing docs.

## Qualitative mode specifics

You are improving a document. Use web search and source reading to find real data and verify claims. One focused improvement per experiment — don't rewrite the document wholesale. The baseline document is in your system prompt as "Current best document."

## When stuck (guardrail active)

If the user prompt contains a guardrail warning, it lists recent failed experiments. Find the assumption they share, then invert it. Do not try a minor variant of a failure. Strategies: ablate, amplify, combine, invert, isolate, simplify, scale, decompose.

## Rules

- Headless. No human interaction.
- Work in your worker dir only.
- Respect your time budget (in user prompt). Orchestrator kills on timeout.
- One idea per experiment.
- Diversify — your role bias exists because parallel workers must not collide.
