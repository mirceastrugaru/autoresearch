Curate the roadmap. This is the most important judge job — the roadmap drives what gets investigated next.

TARGET: {target}

CURRENT ROADMAP:
{roadmap}

WORKER ROADMAP PROPOSALS:
{roadmap_proposals}

ROUND SUMMARY (what was investigated this round):
{round_summary}

---

For each worker proposal, evaluate:
1. **Is it specific enough to assign?** A worker receiving this direction must know exactly what to investigate and what evidence to look for. "Investigate X" is not assignable. "Investigate X by checking Y and Z — if true, it means W" is.
2. **Is it already covered?** Check both the existing roadmap and the round summary. If a direction has been deeply researched, drop it.
3. **Does it matter?** Would confirming or disconfirming this direction change the analysis? If not, drop it.

Produce the updated roadmap:
- Drop duplicates and covered directions.
- Add proposals that pass the three checks above.
- Reorder by impact (directions that would most change the analysis first).
- If a proposal is promising but too vague, rewrite it to be specific before adding.
- If uncertain, add with "[FLAGGED FOR REVIEW]" prefix.
- **Preserve direction IDs.** Existing directions have `[d-xxxx]` prefixes — keep them. For new directions, generate a new ID in the same format (d- followed by 6 hex chars). Every direction in the output must have an ID.
- Format as a flat numbered list under `## Directions`. Each line: `N. [d-xxxx] Direction title`.

Respond ONLY with the full roadmap markdown (not JSON). Start with `# Roadmap`.
