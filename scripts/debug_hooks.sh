#!/usr/bin/env bash
# Debug utility for introspecting hook events
# Usage:
#   ./scripts/debug_hooks.sh start "message"
#   ./scripts/debug_hooks.sh stop

set -euo pipefail

VENV_PYTHON="untracked/venv/bin/python"
BACKUP_FILE=".claude/hooks-daemon.yaml.debug_backup"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Find daemon socket in project's untracked directory
# Supports both suffixed (container) and unsuffixed (desktop) paths
SOCKET_PATH=$(find "$PROJECT_ROOT/.claude/hooks-daemon/untracked/" -name "daemon*.sock" 2>/dev/null | head -n1)

if [[ -z "$SOCKET_PATH" ]]; then
    # Fallback: check for env var override
    SOCKET_PATH="${CLAUDE_HOOKS_SOCKET_PATH:-}"
fi

if [[ -z "$SOCKET_PATH" ]]; then
    echo "ERROR: No daemon socket found in $PROJECT_ROOT/.claude/hooks-daemon/untracked/"
    echo "Is the daemon running? Check: python -m claude_code_hooks_daemon.daemon.cli status"
    exit 1
fi

if [[ ! -f "$VENV_PYTHON" ]]; then
    echo "ERROR: venv Python not found at $VENV_PYTHON"
    exit 1
fi

# Check if we're in debug mode
is_debug_active() {
    [[ -f "$BACKUP_FILE" ]]
}

# Send log marker to daemon
send_log_marker() {
    local message="$1"

    if [[ ! -S "$SOCKET_PATH" ]]; then
        echo "WARNING: Daemon socket not found at $SOCKET_PATH, marker not logged" >&2
        return 1
    fi

    # Send system request to log marker via Python (more reliable than nc)
    cd "$PROJECT_ROOT"
    $VENV_PYTHON -c "
import socket
import json
sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
sock.connect('$SOCKET_PATH')
request = {'event': '_system', 'hook_input': {'action': 'log_marker', 'message': '$message'}}
sock.sendall((json.dumps(request) + '\n').encode())
sock.shutdown(socket.SHUT_WR)
sock.close()
" 2>/dev/null || echo "WARNING: Failed to send marker" >&2
}

case "${1:-}" in
    start)
        # START DEBUG SESSION
        if [[ -z "${2:-}" ]]; then
            echo "ERROR: Please provide boundary message"
            echo "Usage: $0 start \"your message\""
            exit 1
        fi

        BOUNDARY_MSG="$2"

        echo "=== Starting debug session: $BOUNDARY_MSG ==="

        # Enable DEBUG logging via environment variable (no config changes needed)
        if ! is_debug_active; then
            # Create marker file to track debug mode
            touch "$BACKUP_FILE"
            echo "✓ Enabled DEBUG logging via HOOKS_DAEMON_LOG_LEVEL"

            "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
            sleep 1
            # Start daemon with DEBUG log level via environment variable
            HOOKS_DAEMON_LOG_LEVEL=DEBUG "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli start
            sleep 0.5
            echo "✓ Daemon restarted with DEBUG logging"
        else
            echo "✓ DEBUG logging already active"
        fi

        # Insert START boundary marker into daemon logs
        send_log_marker "START BOUNDARY: $BOUNDARY_MSG"
        echo "✓ Boundary marker logged"

        echo ""
        echo "Debug session started. Perform your test actions now."
        echo "When done, run: $0 stop"
        ;;

    stop)
        # STOP DEBUG SESSION
        if ! is_debug_active; then
            echo "ERROR: Not currently in a debug logging session"
            echo "Start one with: $0 start \"message\""
            exit 1
        fi

        echo "=== Stopping debug session ==="

        # Insert END boundary marker into daemon logs
        send_log_marker "END BOUNDARY"
        sleep 0.2  # Give daemon time to log the marker

        # Capture logs and extract between boundaries
        OUTPUT_FILE="/tmp/hook_debug_$(date +%Y%m%d_%H%M%S).log"
        TEMP_LOGS="/tmp/hook_debug_all_$$.log"

        "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli logs --level DEBUG --count 1000 > "$TEMP_LOGS" 2>&1

        # Extract logs between START and END boundaries (inclusive)
        awk '
            /=== START BOUNDARY:/ { capturing=1 }
            capturing { print }
            /=== END BOUNDARY ===/ { capturing=0; exit }
        ' "$TEMP_LOGS" > "$OUTPUT_FILE"

        # Clean up
        rm -f "$TEMP_LOGS" "$BACKUP_FILE"

        # Restart daemon without DEBUG env var (will use config log level)
        "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true
        sleep 1
        "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli start

        echo "✓ Restored config log level"
        echo "✓ Daemon restarted"
        echo ""
        echo "Debug logs saved to: $OUTPUT_FILE"
        echo ""
        echo "=== Debug Log Summary ==="
        cat "$OUTPUT_FILE"
        ;;

    *)
        echo "Hook Debug Utility"
        echo ""
        echo "Usage:"
        echo "  $0 start \"message\"  - Start debug session with boundary message"
        echo "  $0 stop             - Stop session, dump logs, restore INFO level"
        echo ""
        echo "Example:"
        echo "  $0 start \"Testing planning mode hooks\""
        echo "  # ... perform your test actions ..."
        echo "  $0 stop"
        exit 1
        ;;
esac
