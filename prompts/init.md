# init

Headless. No human. Set up the autoresearch project so experiments can run.

## Inputs (from user prompt)

Project dir, autoresearch dir (AR_DIR), eval mode, parallelism.

## Resume

If `AR_DIR/state.json` exists: read it, print a one-line summary, print `INIT RESUMED.` and stop.

## Fresh init

Use absolute paths for all file operations. Paths below are relative to AR_DIR.

1. Read `program.md`. Missing → print `INIT FAILED: program.md not found` and stop.
2. If quantitative mode: read `eval.sh`. Missing → print `INIT FAILED: eval.sh not found` and stop. Make it executable (`chmod +x`) if it isn't.
3. Extract target, directions to prove, directions to disprove, and editable files from program.md.
4. Scaffold `best/` and `branches/main/`:
   - Editable files are listed at their full project-relative paths (e.g. `autoresearch/foo/bar.md`).
   - For each editable file, write it to `best/<that path>` and `branches/main/<that path>`.
   - If the file already exists in the project: copy it.
   - If it doesn't exist: **create a substantive baseline**. For qualitative/document projects, write at minimum 500 words with an outline structured around the prove directions. Don't leave files empty or trivial.
   - **Placeholder framing (qualitative only):** Under each section heading, insert the literal line `*Investigation pending — no findings yet; this section will be populated by research rounds.*`. This tells the judge the section is deliberately empty at baseline.
5. Validate the baseline. Quantitative: run `bash AR_DIR/eval.sh AR_DIR/best/`. Take the last numeric line of stdout as the score. If no numeric line, print `INIT FAILED: eval.sh did not produce a number` and stop. Qualitative: baseline = 0.
6. Write the score to `best_score.txt`.
7. Create empty `log.jsonl`.
8. Create `findings.md` with exactly: `# Findings\n\nNo experiments yet.\n`.
9. Create `roadmap.md` seeded from program.md. Parse `## Directions to prove` and `## Directions to disprove`. Write each entry with its stance and priority (order from program.md = priority, first = highest). Format:
   ```markdown
   # Roadmap

   ## Prove
   1. [direction title] — [rationale from program.md]
   2. [direction title] — [rationale]

   ## Disprove
   1. [direction title] — [rationale from program.md]
   2. [direction title] — [rationale]
   ```
10. Create `branches.jsonl` with one line — a JSON object containing:
    - `branch: "main"`
    - `forked_from: "baseline"`
    - `status: "active"`
    - `created_at: <ISO 8601 UTC timestamp, e.g. "2026-04-13T12:34:56Z">` (compute the real current UTC time, not the literal string "ISO8601")
    - `experiments: 0`
    - `best_score: <the baseline score>`
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
    (`direction` and `strategy` are re-read from program.md each run by the orchestrator — do not write them here.)
12. Print `INIT COMPLETE. Baseline score: {score}`.

## Rules

- Headless. No human interaction.
- Any failure → print the reason and stop. Do not attempt to repair.
- Use absolute paths.
