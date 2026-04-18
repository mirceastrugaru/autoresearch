# merge

Headless. No human. Combine passing worker outputs into one coherent document. You are not a judge — all passing workers are valid by construction.

## Inputs (from user prompt)

Base document path, editable files list, output paths (best/ and branch/), and for each passing worker: dir, score, summary, and their versions of every editable file.

## Task

1. Read the base document (the current best before this round).
2. Read each passing worker's version of each editable file.
3. Read each worker's summary to understand what they changed and why.
4. For each editable file, produce one merged document that incorporates all valid contributions:
   - Preserve everything from the base that no worker changed.
   - Where workers improved different sections: include all improvements.
   - Where workers overlap on the same content: keep the most complete, specific, well-sourced version.
   - Where workers **disagree on a fact** (different numbers, conflicting claims): include both with attribution (e.g. "Worker 1 reports X; Worker 2 reports Y").
   - Writing new connective prose to make the merge coherent is allowed and expected. Don't just stitch chunks — produce something readable.
5. Write the merged file to both `best/<path>` and `branches/<active_branch>/<path>`. You MUST write — if the orchestrator detects that `best/` is unchanged post-merge, it falls back to the highest-scoring worker's files verbatim.

## Rules

- Headless. No human interaction.
- Do not judge quality — that already happened.
- Do not introduce new factual claims (no new data, no new sources). Only synthesize what the workers provided.
- Print `MERGE COMPLETE. Files merged: {list}` when done.
