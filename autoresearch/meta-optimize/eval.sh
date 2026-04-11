#!/bin/bash
#
# Meta-eval: runs the orchestrator on a fresh sort benchmark using the experiment
# prompt from the given directory, and reports the final best score.
#
# Usage: eval.sh <directory-containing-experiment.md>
#
set -e

EVAL_DIR="${1:-.}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEST_DIR="/tmp/autoresearch-meta-eval-$$"

# Set up a fresh sort benchmark
mkdir -p "$TEST_DIR"
cat > "$TEST_DIR/code.py" << 'PYEOF'
"""Sorting benchmark — deliberately slow bubble sort baseline."""
import random
import time

SEED = 42
SIZE = 50000

def generate_data(seed, size):
    rng = random.Random(seed)
    return [rng.randint(0, 1_000_000) for _ in range(size)]

def sort_data(data):
    chunk = data[:2000]
    for i in range(len(chunk)):
        for j in range(0, len(chunk) - i - 1):
            if chunk[j] > chunk[j + 1]:
                chunk[j], chunk[j + 1] = chunk[j + 1], chunk[j]
    rest = sorted(data[2000:])
    return merge(chunk, rest)

def merge(a, b):
    result = []
    i = j = 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1
    result.extend(a[i:])
    result.extend(b[j:])
    return result

if __name__ == "__main__":
    data = generate_data(SEED, SIZE)
    start = time.perf_counter()
    result = sort_data(data)
    elapsed = time.perf_counter() - start
    throughput = SIZE / elapsed
    print(f"{throughput:.2f}")
PYEOF

mkdir -p "$TEST_DIR/autoresearch/meta-test"
cat > "$TEST_DIR/autoresearch/meta-test/program.md" << 'EOF'
# Research Program

## Target
code.py — sorting benchmark

## Metric
Throughput: items sorted per second (higher is better)

## Mode
quantitative

## Parallelism
3

## Editable files
- code.py

## Directions to explore
- Replace bubble sort with faster algorithm
- Use built-in sorted() or list.sort()
- Use numpy arrays
- Minimize allocations
EOF

cat > "$TEST_DIR/autoresearch/meta-test/eval.sh" << 'EVALEOF'
#!/bin/bash
EVAL_DIR="${1:-.}"
python3 "$EVAL_DIR/code.py"
EVALEOF
chmod +x "$TEST_DIR/autoresearch/meta-test/eval.sh"

cat > "$TEST_DIR/autoresearch/meta-test/lockfile.txt" << 'EOF'
eval.sh
program.md
lockfile.txt
EOF

# Copy the experiment prompt being tested into the plugin's prompts dir temporarily
ORIGINAL_PROMPT="$PLUGIN_DIR/prompts/experiment.md"
BACKUP_PROMPT="/tmp/autoresearch-meta-eval-backup-$$.md"
TEST_PROMPT="$EVAL_DIR/experiment.md"
cp "$ORIGINAL_PROMPT" "$BACKUP_PROMPT"
if [ "$(realpath "$TEST_PROMPT")" != "$(realpath "$ORIGINAL_PROMPT")" ]; then
  cp "$TEST_PROMPT" "$ORIGINAL_PROMPT"
fi

# Run 3 rounds
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" /opt/homebrew/bin/python3.13 "$PLUGIN_DIR/bin/orchestrator.py" 3 "$TEST_DIR" meta-test 2>/dev/null

# Get the final score
SCORE=$(cat "$TEST_DIR/autoresearch/meta-test/best_score.txt" 2>/dev/null || echo "0")

# Restore original prompt
cp "$BACKUP_PROMPT" "$ORIGINAL_PROMPT"
rm -f "$BACKUP_PROMPT"

# Clean up
rm -rf "$TEST_DIR"

# Output just the number
echo "$SCORE"
