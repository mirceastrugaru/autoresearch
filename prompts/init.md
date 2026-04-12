# init

Headless. No human. Set up the autoresearch project so experiments can run.

## inputs

Project dir, autoresearch dir, eval mode, parallelism.

## resume

If `state.json` exists: read it, print summary, print "INIT RESUMED." and stop.

## fresh init

All paths below are relative to the autoresearch directory (AR_DIR) provided in the prompt. Use absolute paths for all file operations.

1. Read `AR_DIR/program.md`. Missing → "INIT FAILED: program.md not found" and stop.
2. Read `AR_DIR/eval.sh` (if quantitative mode). Missing → "INIT FAILED: eval.sh not found" and stop.
3. Read the target, directions, and editable files from program.md.
4. Set up `AR_DIR/best/` and `AR_DIR/branches/main/`:
   - If editable files exist in the project dir, copy them in.
   - If they don't exist, **create them.** Read the target and directions in program.md. Write whatever scaffolding is needed — source code, build scripts, config files — so that the eval can run and experiments can iterate. This is the baseline that all workers start from.
5. Run eval on `AR_DIR/best/`. Quantitative: `bash AR_DIR/eval.sh AR_DIR/best/` → must produce a number. Qualitative: skip, baseline = 0.
6. Write `AR_DIR/best_score.txt`.
7. Create empty `AR_DIR/log.jsonl`.
8. Create `AR_DIR/findings.md`: "# Findings\n\nNo experiments yet."
9. Create `AR_DIR/parking_lot.md`: "# Parking Lot\n\nDeferred ideas.\n"
10. Create `AR_DIR/branches.jsonl` with initial entry: `{"branch": "main", "forked_from": "baseline", "status": "active", "created_at": "ISO8601", "experiments": 0, "best_score": 0}`
11. Write `AR_DIR/state.json`:
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
      "strategy": "<competitive|collaborative>",
      "parallelism": <N>
    }
    ```
12. Print "INIT COMPLETE. Baseline score: {score}"

## rules

- Headless. No human interaction.
- If anything fails, print reason and stop.
- Absolute paths from prompt.
