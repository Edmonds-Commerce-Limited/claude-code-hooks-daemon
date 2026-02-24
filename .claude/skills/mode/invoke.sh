#!/usr/bin/env bash
# /mode skill - Get or set daemon operating mode

set -euo pipefail

ARGS="${*:-get}"

cat <<PROMPT
# Daemon Mode - Args: ${ARGS}

View or change the daemon's operating mode.

## Python Path Detection

First, detect the correct Python path:

\`\`\`bash
if [ -f "/workspace/untracked/venv/bin/python" ]; then
    PYTHON="/workspace/untracked/venv/bin/python"
elif [ -f "\$(git rev-parse --show-toplevel 2>/dev/null)/.claude/hooks-daemon/untracked/venv/bin/python" ]; then
    PYTHON="\$(git rev-parse --show-toplevel)/.claude/hooks-daemon/untracked/venv/bin/python"
else
    echo "ERROR: Cannot find hooks daemon Python. Is the daemon installed?"
    exit 1
fi
\`\`\`

## Determine Action from Args

**Args received:** \`${ARGS}\`

Parse the arguments to determine the action:

1. **"get" or empty** -> Run: \`\$PYTHON -m claude_code_hooks_daemon.daemon.cli get-mode\`
2. **"default"** -> Run: \`\$PYTHON -m claude_code_hooks_daemon.daemon.cli set-mode default\`
3. **"unattended"** -> Run: \`\$PYTHON -m claude_code_hooks_daemon.daemon.cli set-mode unattended\`
4. **"unattended <message...>"** -> Run: \`\$PYTHON -m claude_code_hooks_daemon.daemon.cli set-mode unattended -m "<message>"\`

If the first word is "unattended" and there are additional words, join them as the custom message with the -m flag.

## Execute

Run the appropriate CLI command based on the parsed args above. Report the result to the user.

If the daemon is not running, inform the user and suggest starting it:
\`\`\`bash
\$PYTHON -m claude_code_hooks_daemon.daemon.cli start
\`\`\`
PROMPT
