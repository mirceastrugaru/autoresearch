---
description: "Review autoresearch results. Shows what experiments ran, what improved, what failed, and lets you drill into specific experiments."
alwaysApply: false
---

# Autoresearch Review

You are debriefing the human on the results of an autoresearch run.

## Find the initiative

First, check what initiatives exist:

```bash
ls autoresearch/
```

Each subdirectory is a named initiative (e.g. `sort-optimization`, `api-latency`).

- If there's only one, use it automatically.
- If there are multiple, list them with their best scores and ask which one to review:
  ```
  Found 3 research initiatives:
    sort-optimization  — best: 12940933.18 (9 experiments)
    api-latency        — best: 142.00 (30 experiments)  
    parser-accuracy    — best: 0.91 (15 experiments)
  Which one?
  ```
- If the human already specified one (e.g. `/autoresearch:review sort-optimization`), use that.

## Present results

Read these files from `autoresearch/<name>/`:
- `log.jsonl` — every experiment
- `best_score.txt` — current best
- `state.json` — orchestrator state
- `branches.jsonl` — branch history
- `findings.md` — auto-generated summary (if exists)
- `roadmap.md` — curated directions (if exists)

Present a concise summary:

- Starting score vs final best score (and % improvement)
- Total experiments (keeps / discards / thoughts / crashes)
- The kept changes: for each, show experiment ID, parent experiment, hypothesis, and score improvement
- **Experiment genealogy**: show the chain of kept experiments (e.g., #0 → #2 → #5 → #8) so the user can see the lineage of the best result
- Any convergence events (pivots, discard streaks)
- Total API cost if available in state.json
- Remaining parking lot ideas (if any)

## Let them drill in

Ask: "Want to inspect a specific experiment? Give me a number, or say 'done'."

If they give a number, show the full log entry: hypothesis, diff, score, branch, worker.

## Offer to apply

When they're done inspecting, offer:

"The best version of your code is in `autoresearch/<name>/best/`. Want me to copy it back into your project, replacing the original files?"

If yes:
1. **First check git cleanliness** with `git status --porcelain`. If the target files have uncommitted changes, stop and warn: "Target files have uncommitted changes: {list}. Applying would overwrite them. Commit, stash, or explicitly confirm to proceed."
2. Only proceed with explicit confirmation.
3. Copy each file from `autoresearch/<name>/best/` back to its original location (the editable files listed in `program.md`). Show what was copied.

If no, just tell them where the files are.

## Important

- Only modify files if the human explicitly asks to apply the best version.
- If the log is empty: "No experiments have been run yet."
- If no `autoresearch/` directory exists: "No research initiatives found. Run /autoresearch:design to start one."
