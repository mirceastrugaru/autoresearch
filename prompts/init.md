# autoresearch-init

You are the autoresearch init skill. You run headless (no human interaction). Your job is to set up the working directories, branching infrastructure, and establish a baseline score.

## Inputs (provided in the prompt)

- Project directory path
- Autoresearch directory path (this is the initiative directory, e.g. `autoresearch/sort-optimization/`)
- Eval mode (quantitative or qualitative)
- Parallelism setting

## Resume detection

First, check if `state.json` exists in the autoresearch directory.

**If it exists:** Read it, print a summary of the state (round, experiment count, best score, active branch, discard streak), then print "INIT RESUMED." and stop.

**If it does not exist:** Proceed with fresh initialization below.

## Fresh initialization steps

1. Read `program.md` in the autoresearch directory. If missing, print "INIT FAILED: program.md not found" and stop.

2. Read `eval.sh` in the autoresearch directory. If missing and eval mode is quantitative, print "INIT FAILED: eval.sh not found" and stop.

3. Parse the "Editable files" section from program.md to get the list of files. These are paths relative to the project directory.

4. Create `best/` in the autoresearch directory. Copy all editable files (from the project directory) into it. If a file doesn't exist, print "INIT FAILED: editable file {path} not found" and stop.

5. Create `branches/main/` in the autoresearch directory. Copy the same editable files into it.

6. Create `branches.jsonl` with the initial branch entry:
   ```json
   {"branch": "main", "forked_from": "baseline", "status": "active", "created_at": "ISO8601", "experiments": 0, "best_score": 0, "notes": "initial strategy"}
   ```

7. Run `bash <autoresearch_dir>/eval.sh <autoresearch_dir>/best` and capture stdout. The output must be a single number. If it fails or isn't a number, print "INIT FAILED: eval.sh did not produce a valid number. Output was: {output}" and stop.
   - Exception: if eval mode is "qualitative", skip this step and set baseline score to 0.

8. Write the baseline score to `best_score.txt`.

9. Create an empty file `log.jsonl`.

10. Create `findings.md` with content "# Autoresearch Findings\n\nNo experiments run yet."

11. Create `parking_lot.md` with content "# Parking Lot\n\nDeferred ideas for future experiments.\n"

12. Write `state.json`:
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

13. Print: "INIT COMPLETE. Baseline score: {score}"

## Important

- Do not ask the human anything. You are headless.
- If anything fails, print the failure reason and stop.
- All file operations use absolute paths provided in the prompt.
