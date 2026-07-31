#!/bin/bash
#
# daemon.sh — DEPRECATED shim. Use ./bin/hooks-daemon instead.
#
# Plan 00192. This script predates the deployed wrapper and hardcoded
# `untracked/venv/bin/python` — the LEGACY (pre-v3.7.0) venv path, not the
# fingerprint-keyed venv this project actually uses. On a current checkout it
# therefore pointed at an interpreter that may not exist. It also exposed only a
# curated subcommand list rather than forwarding the full CLI.
#
# `bin/hooks-daemon` supersedes it: it resolves the venv through the canonical
# resolver, forwards every subcommand, and anchors to its own location so it
# works from any working directory (including a git worktree).
#
# This shim forwards so existing habits keep working. The deprecation notice
# goes to stderr, never stdout, so anything capturing output is unaffected.

set -euo pipefail

SCRIPT_DIR="$(cd -P "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WRAPPER="$SCRIPT_DIR/bin/hooks-daemon"

if [ ! -x "$WRAPPER" ]; then
    echo "❌ daemon.sh: wrapper missing at $WRAPPER" >&2
    echo "   Run the installer/upgrade to deploy it." >&2
    exit 5
fi

echo "⚠️  daemon.sh is deprecated — use ./bin/hooks-daemon instead." >&2

# The retired script had bespoke log verbs that operated on the log file
# directly. Translate the ones with a CLI equivalent rather than failing on an
# unknown subcommand.
case "${1:-}" in
    logs-tail)
        echo "   'logs-tail' → ./bin/hooks-daemon logs --follow" >&2
        shift
        exec "$WRAPPER" logs --follow "$@"
        ;;
    logs-all)
        # The CLI shows all entries by default.
        echo "   'logs-all' → ./bin/hooks-daemon logs" >&2
        shift
        exec "$WRAPPER" logs "$@"
        ;;
    logs-clear)
        # No CLI equivalent — say so rather than pretending one exists.
        echo "   'logs-clear' has no CLI equivalent." >&2
        echo "   Truncate the log file directly if you need to:" >&2
        echo "     : > \"\$(./bin/hooks-daemon status | awk '/Log/ {print \$NF}')\"" >&2
        exit 2
        ;;
    *)
        exec "$WRAPPER" "$@"
        ;;
esac
