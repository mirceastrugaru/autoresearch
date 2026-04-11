---
description: "Review autoresearch results. Shows what experiments ran, what improved, what failed, and lets you drill into specific experiments."
alwaysApply: false
---

# Autoresearch Review

You are debriefing the human on the results of an autoresearch run.

## Present results

Read these files from the `autoresearch/` directory:
- `log.jsonl` — every experiment
- `best_score.txt` — current best
- `state.json` — orchestrator state
- `branches.jsonl` — branch history
- `findings.md` — auto-generated summary (if exists)

Present a concise summary:

- Starting score vs final best score (and % improvement)
- Total experiments (keeps / discards / thoughts / crashes)
- The kept changes: for each, show experiment ID, hypothesis, and score improvement
- Any convergence events (pivots, discard streaks)
- Total API cost if available in state.json

## Let them drill in

Ask: "Want to inspect a specific experiment? Give me a number, or say 'done'."

If they give a number, show the full log entry: hypothesis, diff, score, branch, worker.

## Offer to apply

When they're done inspecting, offer:

"The best version of your code is in `autoresearch/best/`. Want me to copy it back into your project, replacing the original files?"

If yes, copy each file from `autoresearch/best/` back to its original location (the editable files listed in `program.md`). Show what was copied.

If no, just tell them where the files are.

## Important

- Only modify files if the human explicitly asks to apply the best version.
- If the log is empty: "No experiments have been run yet."
