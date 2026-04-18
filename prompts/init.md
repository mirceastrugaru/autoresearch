# init

Headless. No human. Set up the autoresearch project so experiments can run.

## inputs

Project dir, autoresearch dir, eval mode, parallelism.

## resume

If `state.json` exists: read it, print summary, print "INIT RESUMED." and stop.

## fresh init

1. Read `program.md`. Missing → "INIT FAILED: program.md not found" and stop.
2. Read `eval.sh` (if quantitative mode). Missing → "INIT FAILED: eval.sh not found" and stop.
3. Read the target, directions, and editable files from program.md.
4. Set up `best/` and `branches/main/` in the autoresearch dir:
   - If editable files exist in the project dir, copy them in.
   - If they don't exist, **create them.** Read the target and directions in program.md. Write whatever scaffolding is needed — source code, build scripts, config files — so that the eval can run and experiments can iterate. This is the baseline that all workers start from.
5. Run eval on `best/`. Quantitative: `bash eval.sh best/` → must produce a number. Qualitative: skip, baseline = 0.
6. Write `best_score.txt`.
7. Create empty `log.jsonl`.
8. Create `findings.md`: "# Findings\n\nNo experiments yet."
9. Create `parking_lot.md`: "# Parking Lot\n\nDeferred ideas.\n"
10. Create `branches.jsonl` with initial entry: `{"branch": "main", "forked_from": "baseline", "status": "active", "created_at": "ISO8601", "experiments": 0, "best_score": 0}`
11. Write `state.json`:
    ```json
    {
      "version": 1,
      "round": 0,
      "experiment_count": 0,
      "best_score": <baseline>,
      "active_branch": "main",
      "discard_streak": 0,
      "last_promoted_experiment": 0,
      "best_unchanged_count": 0,
      "last_pivot_experiment": 0,
      "eval_mode": "<quantitative|qualitative>",
      "parallelism": <N>
    }
    ```
12. Print "INIT COMPLETE. Baseline score: {score}"

## rules

- Headless. No human interaction.
- If anything fails, print reason and stop.
- Absolute paths from prompt.
