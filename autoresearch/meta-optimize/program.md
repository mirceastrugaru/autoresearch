# Research Program

## Target
The autoresearch experiment prompt (prompts/experiment.md). This is the instruction set given to each parallel worker agent. Better instructions = agents make smarter hypotheses, waste fewer experiments, and converge faster.

## Metric
Final best score achieved on a fixed sorting benchmark after exactly 3 rounds (9 experiments). Higher is better. The benchmark starts from a deliberately slow bubble sort implementation — there's a known ceiling around 60M items/sec with numpy. The baseline experiment prompt gets to about 5-13M in 3 rounds. A better prompt should get closer to the ceiling.

## Mode
quantitative

## Parallelism
3

## Editable files
- prompts/experiment.md

## Directions to explore
- Make the agent read the code more carefully before making changes (currently some agents make blind guesses)
- Tell the agent to prioritize algorithmic changes over micro-optimizations in early experiments
- Add instructions about learning from the log — what patterns of previous experiments succeeded vs failed
- Tell the agent to avoid repeating approaches that other parallel workers likely also tried (e.g. if the obvious first move is "replace bubble sort", all 3 workers do it — wasted parallelism)
- Add differentiation instructions: worker-1 should try conservative changes, worker-2 moderate, worker-3 aggressive
- Tell agents to consider numpy/native extensions early since that's where the big wins are
- Reduce verbosity in the prompt to save tokens
- Remove instructions the agents ignore anyway
