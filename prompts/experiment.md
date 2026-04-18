# experiment

Headless. No human. One invocation = one experiment. Isolated worker directory.

## inputs

Provided in system prompt: program.md, findings.md, full log, parking_lot.md, current best document.
Provided in user prompt: experiment ID, worker dir, autoresearch dir, eval command, branch, best score, parent experiment, guardrail warning (if any).

## steps

1. READ: system prompt already contains program.md, findings.md, full log, parking_lot.md, current best. Read `branches.jsonl` from disk if you need branch history beyond what's in the log.
2. THINK: what has been tried? what failed? what's in the parking lot? what untested direction exists? → decide hypothesis
3. THOUGHT EXPERIMENT (optional): if conclusive without testing → write `thought` to `status.txt`, analysis to `hypothesis.txt`, `0` to `score.txt`, skip to step 9
4. HYPOTHESIS: one sentence, write to `hypothesis.txt`
5. EDIT: editable files are listed in program.md as project-relative paths (e.g. `autoresearch/myproject/analysis.md`). They live at that same relative path inside your worker dir (e.g. `worker_dir/autoresearch/myproject/analysis.md`). Edit them there. Never edit eval.sh/lockfile.txt/program.md/state.json/log.jsonl/branches.jsonl/findings.md/parking_lot.md or parking_lot_*.txt files.
6. DIFF: write text diff to `diff.txt`
7. EVAL: run eval command. write number to `score.txt`. write `real` to `status.txt`
8. SUMMARY: write a paragraph to `summary.txt` — what you changed, what the result showed, what was surprising or notable. This is the record future workers will learn from.
9. PARKING LOT: write any deferred ideas to `parking_lot_<worker_number>.txt` (e.g. `parking_lot_1.txt` for worker-1). One idea per line. The orchestrator will merge these safely. Draw from the parking_lot.md in your system prompt — if an idea there is relevant to your experiment, note whether you tested it and what you found.
10. write parent experiment number to `parent.txt`
11. LAST ACTION: write experiment ID to `experiment_id_output.txt`

## scoring

You are scored against the rubric in program.md. Read it. Understand the gates. Fail a hard gate → your work is discarded regardless of other quality. The judge is an LLM with web search — it will verify claims.

In collaborative mode: you do not need to beat the current best score. You need to pass hard gates. Any work that passes hard gates is valid and will be merged into the baseline.

## qualitative mode

If program.md mode=qualitative: you improve a document, not code. Use web search to find real data, read source code, verify claims. Each experiment = one focused improvement. Don't rewrite everything.

## when stuck (guardrail active)

The guardrail message in your user prompt lists recent failed experiments. Identify what assumption they share. Invert it. Check parking_lot.md.

Strategies: ablation (remove), amplification (push further), combination (merge wins), inversion (opposite), isolation (one var), simplification (reduce), scaling (order of magnitude), decomposition (split).

## rules

- headless, no human interaction
- worker dir only
- no repeating logged experiments
- one idea per experiment
- print "EXPERIMENT COMPLETE. Score: {score}" or "THOUGHT EXPERIMENT COMPLETE." when done
