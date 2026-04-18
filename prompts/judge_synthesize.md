Synthesize the next version of the main document from all worker write-ups this round.

TARGET: {target}

CURRENT MAIN DOCUMENT:
{current_doc}

WORKER WRITE-UPS THIS ROUND (with scores):
{writeups_with_scores}

---

Read all supportive write-ups (evidence consistent with directions) and adversarial write-ups (evidence inconsistent). Produce the next version of the main document that:
- Incorporates consistent evidence into the appropriate sections.
- Addresses inconsistent evidence — either with counter-evidence, acknowledging it as a limitation, or revising claims.
- Does not suppress evidence from either stance.
- Maintains all existing content that wasn't contradicted.
- ONLY includes sections with actual evidence. No placeholder sections.
- Each worker's contribution: at most 150 words. State the finding, the strongest evidence, and the source. 50 words is better than 150 if the point is clear.

One editable file per entry in the editable files list.

Respond ONLY with JSON:
{{
  "editable/file/path.md": "full updated document content"
}}
