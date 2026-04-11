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

# Check API key
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo ""
  echo "NOTE: ANTHROPIC_API_KEY is not set."
  echo "  The slash commands work without it."
  echo "  The orchestrator needs it. Get one at:"
  echo "  https://console.anthropic.com/settings/keys"
  echo ""
  echo "  Add to your shell profile:"
  echo "    export ANTHROPIC_API_KEY=sk-ant-api03-..."
fi

# Find the install path
INSTALL_PATH=$(claude plugins list 2>&1 | grep -A1 autoresearch | grep installPath | sed 's/.*: //' || echo "")
if [ -z "$INSTALL_PATH" ]; then
  INSTALL_PATH="(run 'claude plugins list' to find the install path)"
fi

echo ""
echo "Done. Restart Claude Code to load the plugin."
echo ""
echo "Commands available after restart:"
echo "  /autoresearch:design   — set up a new research project"
echo "  /autoresearch:review   — review experiment results"
echo ""
echo "To run experiments:"
if [ -n "$PYTHON_CMD" ]; then
  echo "  ANTHROPIC_API_KEY=sk-... $PYTHON_CMD $INSTALL_PATH/bin/orchestrator.py <rounds> <project-dir>"
else
  echo "  ANTHROPIC_API_KEY=sk-... python3.13 <install-path>/bin/orchestrator.py <rounds> <project-dir>"
fi
