#!/usr/bin/env bash
# /mode skill - Get or set daemon operating mode

set -euo pipefail

ARGS="${*:-get}"

cat <<PROMPT
# Daemon Mode - Args: ${ARGS}

View or change the daemon's operating mode.

## Locate the daemon CLI wrapper

There is no interpreter to detect. The deployed \`bin/hooks-daemon\` wrapper
resolves the fingerprint-keyed venv itself. Resolve the wrapper once, from the
project root:

\`\`\`bash
PROJECT_ROOT="\$(git rev-parse --show-toplevel)"
if [ -x "\$PROJECT_ROOT/.claude/hooks-daemon/bin/hooks-daemon" ]; then
    DAEMON_CLI="\$PROJECT_ROOT/.claude/hooks-daemon/bin/hooks-daemon"   # normal install
elif [ -x "\$PROJECT_ROOT/bin/hooks-daemon" ]; then
    DAEMON_CLI="\$PROJECT_ROOT/bin/hooks-daemon"                        # self-install
else
    echo "ERROR: bin/hooks-daemon wrapper not found. Is the daemon installed?" >&2
    exit 1
fi
\`\`\`

## Determine Action from Args

**Args received:** \`${ARGS}\`

Parse the arguments to determine the action:

1. **"get" or empty** -> Run: \`"\$DAEMON_CLI" get-mode\`
2. **"default"** -> Run: \`"\$DAEMON_CLI" set-mode default\`
3. **"unattended"** -> Run: \`"\$DAEMON_CLI" set-mode unattended\`
4. **"unattended <message...>"** -> Run: \`"\$DAEMON_CLI" set-mode unattended -m "<message>"\`

If the first word is "unattended" and there are additional words, join them as the custom message with the -m flag.

## Execute

Run the appropriate CLI command based on the parsed args above. Report the result to the user.

If the daemon is not running, inform the user and suggest starting it:
\`\`\`bash
"\$DAEMON_CLI" start
\`\`\`
PROMPT
