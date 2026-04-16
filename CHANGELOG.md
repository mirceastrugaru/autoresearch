# Changelog

## 2026-04-16

### Pending-vector placeholders
Init now writes a literal `*Investigation pending*` line under each vector heading, and the judge prompt treats those placeholders as deliberately empty rather than as missing evidence. Addresses the observed ~25% hard-gate failure rate where workers only touched their assigned vector and the evidence gate zeroed them for the untouched vectors it wasn't their job to populate.

### Bias rotation across workers
Vector-aware assignment now spreads CONSERVATIVE/MODERATE/AGGRESSIVE across the workers within each round. Previously the tuple scoring tied on cold-start rounds and the bias loop's declaration order meant every worker in round 1 got CONSERVATIVE. Fix penalizes biases already chosen by prior workers in the same round — round 1 of a 5-vector/3-worker run now produces (CONSERVATIVE, MODERATE, AGGRESSIVE) across the three workers instead of all CONSERVATIVE. Over 15 slots the distribution is now even (5/5/5) versus the previous ~7/5/3.

### Merge timeout
Configurable timeout (`AUTORESEARCH_MERGE_TIMEOUT`, default 300s) around merge agent calls. When a merge hangs — observed on two initiatives where the API call never returned — the orchestrator kills it and falls back to the best-scoring worker's files instead of blocking forever.

### Lightweight workers in collaborative mode
Workers no longer receive the full best document in their system prompt. They get the experiment log, program.md, findings, and parking lot — enough to avoid duplication. The merge agent remains the only one reading the full document. Removes the context ceiling where growing documents starved workers of research capacity by round 3-4.

### Vector-aware worker assignment
Orchestrator parses research vectors from program.md, builds a coverage matrix from the log, and assigns each worker a specific (vector, bias) pair that fills the largest gap. Eliminates the convergence problem where all workers self-selected the same topic.

## 2026-04-15

### Web monitor
Real-time browser dashboard (`bin/monitor.py`) showing round progress, worker status, scores, and token usage.

### Background merge pipeline
Merge agent runs concurrently with the next round's workers instead of blocking between rounds. Cuts wall-clock time by overlapping merge and worker execution.

## 2026-04-13

### Competitive/collaborative strategy
Competitive mode promotes the single best worker per round. Collaborative mode passes all workers that clear hard gates to a merge agent that integrates findings into one document.

### Rubric enforcement
Locked rubric structure: exactly two hard gates (correctness, evidence), four universal soft gates, plus optional custom soft gates. Validated at startup.

### Server-side diffs and trace capture
Orchestrator computes diffs from filesystem snapshots instead of trusting worker-reported diffs. Full SDK message streams captured as JSONL trace files per worker.

### Worker diversification
Role biases (CONSERVATIVE, MODERATE, AGGRESSIVE) shape risk appetite. Parking lot ideas distributed as seeds. Guardrail messages with failure analysis trigger after discard streaks.

## 2026-04-12

### Prompt caching
Shared context (program.md, log, findings, best document) injected into system prompt so parallel workers get cache hits on identical content instead of each reading files independently.

### Debug log
Structured JSONL debug log wired throughout the orchestrator — round starts, worker launches, results, merges, pivots, timing.

## 2026-04-11

### Initial release
Autoresearch framework: parallel workers, eval loop, named initiatives, quantitative and qualitative eval modes (LLM-as-judge with gated scoring), parking lot for deferred ideas, experiment genealogy, forced pivots after discard streaks, periodic revalidation.
