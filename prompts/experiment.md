# experiment

Headless. No human. One invocation = one experiment. Isolated worker directory.

## inputs

Provided in prompt: experiment ID, worker dir, autoresearch dir, eval command, branch, best score, parent experiment, guardrail warning (if any).

## steps

1. READ: `program.md` (directions, editable files, rubric), `log.jsonl` (last 10), `findings.md`, `parking_lot.md`, `branches.jsonl`
2. THINK: convergence signals? untested assumptions? invalidation risk? parking lot ideas? → decide hypothesis
3. THOUGHT EXPERIMENT (optional): if conclusive without testing → write `thought` to `latest_status.txt`, analysis to `latest_hypothesis.txt`, `0` to `latest_score.txt`, skip to step 8
4. HYPOTHESIS: one sentence, write to `latest_hypothesis.txt`
5. EDIT: worker dir files only. only files listed editable in program.md. never edit eval.sh/lockfile.txt/program.md/state.json/log.jsonl/branches.jsonl/findings.md/parking_lot.md
6. DIFF: write text diff to `latest_diff.txt`
7. EVAL: run eval command. write number to `latest_score.txt`. write `real` to `latest_status.txt`
8. REFLECT: what confirmed/surprised? ideas for later → append to `parking_lot.md`. write parent to `latest_parent.txt`
9. LAST ACTION: write experiment ID to `experiment_id_output.txt`

## scoring

You are scored against the rubric in program.md. Read it. Understand the gates. Fail a hard gate → your work is discarded regardless of other quality. The judge is an LLM with web search — it will verify claims.

## qualitative mode

If program.md mode=qualitative: you improve a document, not code. Use web search to find real data, read source code, verify claims. Each experiment = one focused improvement. Don't rewrite everything.

## when stuck (guardrail active)

List assumptions of current strategy. Invert one. Check parking lot.

Strategies: ablation (remove), amplification (push further), combination (merge wins), inversion (opposite), isolation (one var), simplification (reduce), scaling (order of magnitude), decomposition (split).

## rules

- headless, no human interaction
- worker dir only
- no repeating logged experiments
- one idea per experiment
- print "EXPERIMENT COMPLETE. Score: {score}" or "THOUGHT EXPERIMENT COMPLETE." when done
