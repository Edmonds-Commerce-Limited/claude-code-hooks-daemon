#!/usr/bin/env bash
# /configure skill - View and modify hooks daemon handler configuration

set -euo pipefail

ARGS="${*:-summary}"

cat <<PROMPT
# Configure Hooks Daemon - Args: ${ARGS}

View or modify the hooks daemon handler configuration.

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

## Config File Location

Find the config file:

\`\`\`bash
PROJECT_ROOT=\$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
CONFIG="\${PROJECT_ROOT}/.claude/hooks-daemon.yaml"

if [ ! -f "\$CONFIG" ]; then
    echo "ERROR: Config file not found at \$CONFIG"
    exit 1
fi
\`\`\`

## Determine Action from Args

**Args received:** \`${ARGS}\`

Parse the arguments to determine the action:

1. **No args or "summary"** -> Show config summary
2. **"list"** -> List all handlers with their configurable options
3. **Single word (handler name)** -> Show config for that handler
4. **Handler name + option=value** -> Set the option on that handler

## Action: Show Summary (if args = "summary" or empty)

1. Read \`.claude/hooks-daemon.yaml\`
2. Display daemon settings section (log_level, idle_timeout_seconds, strict_mode, etc.)
3. For each event type (pre_tool_use, post_tool_use, session_start, etc.):
   - List all handlers with their enabled status and priority
   - Use a compact format: \`handler_name: enabled=true priority=10\`
4. Show count of enabled vs disabled handlers

## Action: List Handlers (if args = "list")

1. Read \`.claude/hooks-daemon.yaml\`
2. Read @docs/guides/HANDLER_REFERENCE.md for handler descriptions
3. For each handler across all event types, display:
   - Config key, event type, enabled/disabled, priority
   - Handler type (Blocking/Advisory)
   - Any configurable options with current and default values
4. Highlight which handlers have configurable options:
   - **sed_blocker**: \`blocking_mode\` (strict | direct_invocation_only) [default: strict]
   - **git_stash**: \`mode\` (warn | deny) [default: warn]
   - **markdown_organization**: \`track_plans_in_project\`, \`plan_workflow_docs\`, \`allowed_markdown_paths\`, \`monorepo_subproject_patterns\`
   - **plan_number_helper**: \`track_plans_in_project\`, \`plan_workflow_docs\` (inherits from markdown_organization)

## Action: Show Handler (if args = single handler name)

1. Read \`.claude/hooks-daemon.yaml\`
2. Search all event type sections for the handler config key
3. If not found, suggest similar handler names (fuzzy match)
4. Display:
   - Event type, enabled status, priority
   - Handler type (Blocking/Advisory) from HANDLER_REFERENCE.md
   - Description from HANDLER_REFERENCE.md
   - Current options (if any set in config)
   - Available options with defaults (from source code / HANDLER_REFERENCE.md)
   - Example config YAML snippet

## Action: Set Option (if args = handler name + option=value)

1. Read \`.claude/hooks-daemon.yaml\`
2. Find the handler in the config (search all event type sections)
3. If handler not found, report error with suggestion
4. Parse the option=value pair:
   - **enabled=true|false**: Set the \`enabled\` field directly on the handler
   - **priority=N**: Set the \`priority\` field directly on the handler (validate it's an integer)
   - **Any other key**: Set under the handler's \`options:\` sub-block
5. Use the Edit tool to modify \`.claude/hooks-daemon.yaml\`:
   - If handler uses compact syntax \`{enabled: true, priority: 10}\`, expand to block syntax when adding options
   - If handler already has block syntax, add/update the option
   - For options under \`options:\` block, create the block if it doesn't exist
6. After editing, restart daemon and verify:

\`\`\`bash
\$PYTHON -m claude_code_hooks_daemon.daemon.cli restart
\$PYTHON -m claude_code_hooks_daemon.daemon.cli status
# Expected: Status: RUNNING
\`\`\`

7. Report result:
   - What was changed
   - Daemon status after restart
   - Any warnings

## Important Notes

- **Always preserve existing YAML comments** when editing the config
- **Always restart daemon** after any config change
- **Always verify daemon is RUNNING** after restart
- Handler options are set via \`setattr(instance, f"_{option_key}", option_value)\` in the registry, so config key \`blocking_mode\` maps to handler attribute \`_blocking_mode\`
- The \`options:\` block in config is a flat dict of key-value pairs applied to the handler instance

## Reference Documentation

- Config syntax: @docs/guides/CONFIGURATION.md
- Handler options: @docs/guides/HANDLER_REFERENCE.md
- Handler per-handler docs: @docs/guides/handlers/ (where available)

Begin by reading the config file and determining the action from the args.
PROMPT
