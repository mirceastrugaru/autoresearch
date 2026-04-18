# merge

Headless. No human. Combine passing worker outputs into one coherent document.

## inputs

Provided in prompt: base document path, list of passing workers (directory, score, summary), output paths (best/ and branch/).

## task

1. Read the base document (current best before this round)
2. Read each passing worker's version of each editable file
3. Read each worker's summary to understand what they changed and why
4. For each editable file: produce one merged document that incorporates all valid contributions from all passing workers
   - Preserve everything from the base that no worker changed
   - Where workers improved different sections: include all improvements
   - Where workers overlap on the same content: keep the most complete, specific, well-sourced version
   - Do not discard any valid contribution — the goal is accumulation, not selection
5. Write the merged file to best/ and branches/<active_branch>/

## rules

- Headless. No human interaction.
- Do not judge quality — that already happened. Your job is to combine.
- Do not add new content — only merge what the workers produced.
- Print "MERGE COMPLETE. Files merged: {list}" when done.
