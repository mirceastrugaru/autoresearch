#!/bin/bash
#
# Installs the autoresearch plugin into Claude Code permanently.
# After running this, /autoresearch:design and /autoresearch:review
# are available in every Claude Code session.
#
set -e

PLUGIN_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_NAME="autoresearch@local"
CLAUDE_DIR="$HOME/.claude"
PLUGINS_FILE="$CLAUDE_DIR/plugins/installed_plugins.json"
SETTINGS_FILE="$CLAUDE_DIR/settings.json"

echo "Installing autoresearch plugin..."
echo "  Plugin directory: $PLUGIN_DIR"

# Check Claude Code is installed
if ! command -v claude &>/dev/null; then
  echo ""
  echo "ERROR: Claude Code not found."
  echo "  Install it from: https://claude.ai/code"
  exit 1
fi

# Validate plugin
claude plugins validate "$PLUGIN_DIR" 2>/dev/null || {
  echo "ERROR: Plugin validation failed."
  exit 1
}

# Ensure plugins directory exists
mkdir -p "$CLAUDE_DIR/plugins"

# Register in installed_plugins.json
if [ ! -f "$PLUGINS_FILE" ]; then
  echo '{"version": 2, "plugins": {}}' > "$PLUGINS_FILE"
fi

python3 -c "
import json, sys
from datetime import datetime, timezone

plugins_file = '$PLUGINS_FILE'
plugin_name = '$PLUGIN_NAME'
plugin_dir = '$PLUGIN_DIR'

with open(plugins_file) as f:
    data = json.load(f)

data['plugins'][plugin_name] = [{
    'scope': 'user',
    'installPath': plugin_dir,
    'version': '0.1.0',
    'installedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    'lastUpdated': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
}]

with open(plugins_file, 'w') as f:
    json.dump(data, f, indent=2)

print('  Registered in installed_plugins.json')
"

# Enable in settings.json
if [ ! -f "$SETTINGS_FILE" ]; then
  echo '{}' > "$SETTINGS_FILE"
fi

python3 -c "
import json

settings_file = '$SETTINGS_FILE'
plugin_name = '$PLUGIN_NAME'

with open(settings_file) as f:
    data = json.load(f)

if 'enabledPlugins' not in data:
    data['enabledPlugins'] = {}

data['enabledPlugins'][plugin_name] = True

with open(settings_file, 'w') as f:
    json.dump(data, f, indent=2)

print('  Enabled in settings.json')
"

# Check Python requirements
echo ""
PYTHON_CMD=""
for cmd in python3.13 python3.12 python3.11 python3.10 python3; do
  if command -v "$cmd" &>/dev/null; then
    version=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
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
  echo "  The slash commands (/autoresearch:design, /autoresearch:review) will work."
  echo "  But the orchestrator needs Python 3.10+."
  echo "  Install: brew install python@3.13"
else
  echo "Python: $PYTHON_CMD ($version)"

  # Check claude-agent-sdk
  if ! "$PYTHON_CMD" -c "import claude_agent_sdk" 2>/dev/null; then
    echo ""
    echo "Installing claude-agent-sdk..."
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

echo ""
echo "Done. Restart Claude Code to load the plugin."
echo ""
echo "Commands available after restart:"
echo "  /autoresearch:design   — set up a new research project"
echo "  /autoresearch:review   — review experiment results"
echo ""
echo "To run experiments:"
echo "  $PYTHON_CMD $PLUGIN_DIR/bin/orchestrator.py <rounds> <project-dir>"
