#!/bin/bash
#
# Claude Code Hooks Daemon - Lifecycle Management Script
#
# Simple wrapper around the daemon CLI for quick lifecycle operations.
# Automatically detects project path and uses venv Python.
#

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Get script directory (daemon repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Python command from venv with proper PYTHONPATH
VENV_PYTHON="$SCRIPT_DIR/untracked/venv/bin/python"

# Check if venv exists
if [[ ! -f "$VENV_PYTHON" ]]; then
    echo -e "${RED}ERROR: Virtual environment not found${NC}" >&2
    echo "Run: cd $SCRIPT_DIR && uv sync" >&2
    exit 1
fi

# Set PYTHONPATH to include src directory
export PYTHONPATH="$SCRIPT_DIR/src:${PYTHONPATH:-}"

# Python command wrapper
PYTHON_CMD="$VENV_PYTHON"

# Daemon CLI module
DAEMON_CLI="claude_code_hooks_daemon.daemon.cli"

# Usage message
usage() {
    cat <<EOF
Usage: $(basename "$0") <command>

Daemon Lifecycle Commands:
  start         Start the daemon
  stop          Stop the daemon
  restart       Restart the daemon
  status        Check daemon status

Log Commands:
  logs          Show recent daemon logs (tail -50)
  logs-tail     Follow daemon logs in real-time
  logs-all      Show all daemon logs
  logs-clear    Clear daemon logs

Examples:
  ./daemon.sh start          # Start daemon
  ./daemon.sh status         # Check if running
  ./daemon.sh logs-tail      # Watch logs in real-time
  ./daemon.sh restart        # Restart daemon

EOF
    exit 1
}

# Get log file path from Python
get_log_path() {
    $PYTHON_CMD -c "
from claude_code_hooks_daemon.daemon.paths import get_log_path
import os
print(get_log_path(os.getcwd()))
" 2>/dev/null
}

# Main command dispatcher
case "${1:-}" in
    start)
        echo -e "${BLUE}Starting daemon...${NC}"
        $PYTHON_CMD -m $DAEMON_CLI start
        ;;

    stop)
        echo -e "${BLUE}Stopping daemon...${NC}"
        $PYTHON_CMD -m $DAEMON_CLI stop
        ;;

    restart)
        echo -e "${BLUE}Restarting daemon...${NC}"
        $PYTHON_CMD -m $DAEMON_CLI restart
        ;;

    status)
        $PYTHON_CMD -m $DAEMON_CLI status
        ;;

    logs)
        LOG_PATH=$(get_log_path)
        if [[ -f "$LOG_PATH" ]]; then
            echo -e "${BLUE}Recent daemon logs (last 50 lines):${NC}"
            echo -e "${YELLOW}Log file: $LOG_PATH${NC}"
            echo "---"
            tail -50 "$LOG_PATH"
        else
            echo -e "${YELLOW}No log file found at: $LOG_PATH${NC}"
        fi
        ;;

    logs-tail)
        LOG_PATH=$(get_log_path)
        if [[ -f "$LOG_PATH" ]]; then
            echo -e "${BLUE}Following daemon logs (Ctrl+C to stop):${NC}"
            echo -e "${YELLOW}Log file: $LOG_PATH${NC}"
            echo "---"
            tail -f "$LOG_PATH"
        else
            echo -e "${YELLOW}No log file found at: $LOG_PATH${NC}"
            echo "Logs will appear here once daemon starts..."
            # Wait for log file to be created
            while [[ ! -f "$LOG_PATH" ]]; do
                sleep 1
            done
            tail -f "$LOG_PATH"
        fi
        ;;

    logs-all)
        LOG_PATH=$(get_log_path)
        if [[ -f "$LOG_PATH" ]]; then
            echo -e "${BLUE}All daemon logs:${NC}"
            echo -e "${YELLOW}Log file: $LOG_PATH${NC}"
            echo "---"
            cat "$LOG_PATH"
        else
            echo -e "${YELLOW}No log file found at: $LOG_PATH${NC}"
        fi
        ;;

    logs-clear)
        LOG_PATH=$(get_log_path)
        if [[ -f "$LOG_PATH" ]]; then
            > "$LOG_PATH"
            echo -e "${GREEN}✓ Daemon logs cleared${NC}"
        else
            echo -e "${YELLOW}No log file to clear${NC}"
        fi
        ;;

    *)
        usage
        ;;
esac
