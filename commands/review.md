---
description: "Review autoresearch results. Shows what experiments ran, what improved, what failed, and lets you drill into specific experiments."
alwaysApply: false
---

# Autoresearch Review

You are debriefing the human on the results of an autoresearch run. This is read-only — do not modify any files.

## Steps

1. Read `autoresearch/log.jsonl` and parse all entries.
2. Read `autoresearch/findings.md`.
3. Read `autoresearch/best_score.txt`.
4. Read `autoresearch/state.json` for orchestrator state.
5. Read `autoresearch/branches.jsonl` for branch history.

6. Present a summary:

```
## Autoresearch Results

- Rounds completed: N
- Total experiments: N (keeps: N, discards: N, thoughts: N, crashes: N)
- Starting score: {baseline}
- Final best score: {current best}
- Score improvement: {delta} ({percentage}%)
- Total API cost: (from state.json if available)

### Branch history
- main: N experiments, best score N
- pivot-15: N experiments, best score N (reason for pivot)

### Kept changes
For each: experiment ID, branch, hypothesis, score, delta from previous best

### Discarded changes
For each: experiment ID, branch, hypothesis, score

### Thought experiments
For each: experiment ID, conclusion

### Convergence events
- Pivots: when and why
- Longest discard streak
- Revalidation results

### Flagged for review
Any experiments with suspiciously large improvement (>50% in one step)
```

7. Ask: "Do you want to inspect any specific experiment in detail? (Give me an experiment number, or say 'no')"

8. If the human gives a number:
   - Show the full log entry
   - Show hypothesis, diff, score change
   - Show branch and worker
   - Ask if they want to see another

9. If no: "Review complete. Best code is in autoresearch/best/."

## Important

- Read-only. Do not modify any files.
- If the log is empty: "No experiments have been run yet."
