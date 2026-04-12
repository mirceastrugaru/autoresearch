#!/bin/bash
#
# Installs the autoresearch plugin into Claude Code permanently.
# After running this, /autoresearch:design and /autoresearch:review
# are available in every Claude Code session.
#
set -e

echo "Installing autoresearch plugin..."

# Check Claude Code is installed
if ! command -v claude &>/dev/null; then
  echo ""
  echo "ERROR: Claude Code not found."
  echo "  Install it from: https://claude.ai/code"
  exit 1
fi

# Add marketplace and install plugin
echo "  Adding marketplace..."
claude plugins marketplace add https://github.com/mirceastrugaru/autoresearch.git 2>&1 | grep -E "✔|✘|already"

echo "  Installing plugin..."
claude plugins install autoresearch@autoresearch-marketplace --scope user 2>&1 | grep -E "✔|✘|already"

# Check Python requirements
echo ""
PYTHON_CMD=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cmd" &>/dev/null; then
    major=$("$cmd" -c "import sys; print(sys.version_info.major)")
    minor=$("$cmd" -c "import sys; print(sys.version_info.minor)")
    if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
      PYTHON_CMD="$cmd"
      break
    fi
  fi
done

if [ -z "$PYTHON_CMD" ]; then
  echo "WARNING: Python 3.10+ not found."
  echo "  The slash commands work without it."
  echo "  The orchestrator needs Python 3.10+."
  echo "  Install: brew install python@3.13"
else
  echo "Python: $PYTHON_CMD ($major.$minor)"

  if ! "$PYTHON_CMD" -c "import claude_agent_sdk" 2>/dev/null; then
    echo "  Installing claude-agent-sdk..."
    "$PYTHON_CMD" -m pip install claude-agent-sdk 2>&1 | tail -1
  else
    echo "claude-agent-sdk: installed"
  fi
fi

# No API key needed — orchestrator uses Claude Code's existing auth via the Agent SDK.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "Done. Restart Claude Code to load the plugin."
echo ""
echo "Commands available after restart:"
echo "  /autoresearch:design   — set up a new research project"
echo "  /autoresearch:review   — review experiment results"
echo ""
echo "To run experiments:"
echo "  ANTHROPIC_API_KEY=sk-... ${PYTHON_CMD:-python3.13} $SCRIPT_DIR/bin/orchestrator.py <rounds> <project-dir>"
