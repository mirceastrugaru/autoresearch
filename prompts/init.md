# autoresearch-init

You are the autoresearch init skill. You run headless (no human interaction). Your job is to set up the working directories, branching infrastructure, and establish a baseline score.

## Inputs (provided in the prompt)

- Project directory path
- Autoresearch directory path
- Eval mode (quantitative or qualitative)
- Parallelism setting

## Resume detection

First, check if `autoresearch/state.json` exists.

**If it exists:** Read it, print a summary of the state (round, experiment count, best score, active branch, discard streak), then print "INIT RESUMED." and stop. The orchestrator will pick up from the saved state.

**If it does not exist:** Proceed with fresh initialization below.

## Fresh initialization steps

1. Read `autoresearch/program.md`. If missing, print "INIT FAILED: autoresearch/program.md not found" and stop.

2. Read `autoresearch/eval.sh`. If missing and eval mode is quantitative, print "INIT FAILED: autoresearch/eval.sh not found" and stop.

3. Parse the "Editable files" section from program.md to get the list of files.

4. Create `autoresearch/best/`. Copy all editable files into it. If a file doesn't exist, print "INIT FAILED: editable file {path} not found" and stop.

5. Create `autoresearch/branches/main/`. Copy the same editable files into it.

6. Create `autoresearch/branches.jsonl` with the initial branch entry:
   ```json
   {"branch": "main", "forked_from": "baseline", "status": "active", "created_at": "ISO8601", "experiments": 0, "best_score": 0, "notes": "initial strategy"}
   ```

7. Run `bash autoresearch/eval.sh autoresearch/best` and capture stdout. The output must be a single number. If it fails or isn't a number, print "INIT FAILED: eval.sh did not produce a valid number. Output was: {output}" and stop.
   - Exception: if eval mode is "qualitative", skip this step and set baseline score to 0.

8. Write the baseline score to `autoresearch/best_score.txt`.

9. Create an empty file `autoresearch/log.jsonl`.

10. Create `autoresearch/findings.md` with content "# Autoresearch Findings\n\nNo experiments run yet."

11. Write `autoresearch/state.json`:
    ```json
    {
      "version": 1,
      "round": 0,
      "experiment_count": 0,
      "best_score": <baseline>,
      "active_branch": "main",
      "discard_streak": 0,
      "best_unchanged_count": 0,
      "last_pivot_experiment": 0,
      "eval_mode": "<quantitative|qualitative>",
      "parallelism": <N>
    }
    ```

12. Print: "INIT COMPLETE. Baseline score: {score}"

## Important

- Do not ask the human anything. You are headless.
- If anything fails, print the failure reason in the exact format above and stop.
- Use absolute paths provided in the prompt.
