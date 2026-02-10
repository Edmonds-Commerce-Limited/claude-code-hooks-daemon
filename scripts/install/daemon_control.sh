#!/bin/bash
#
# daemon_control.sh - Unified daemon lifecycle management
#
# Provides safe daemon start, stop, restart, and status checking.
# Handles error cases gracefully and provides clear feedback.
#
# Usage:
#   source "$(dirname "$0")/lib/daemon_control.sh"
#   stop_daemon_safe "$VENV_PYTHON"
#   start_daemon_safe "$VENV_PYTHON"
#   restart_daemon_verified "$VENV_PYTHON"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# stop_daemon_safe() - Safely stop the daemon
#
# Stops daemon without failing if it's not running.
# Suppresses errors for clean stop operation.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#
# Returns:
#   Exit code 0 always (errors are suppressed)
#
stop_daemon_safe() {
    local venv_python="$1"

    if [ -z "$venv_python" ]; then
        print_warning "stop_daemon_safe: venv_python parameter required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_verbose "Venv Python not found, skipping daemon stop: $venv_python"
        return 0
    fi

    print_verbose "Stopping daemon..."

    # Stop daemon, ignore errors (daemon may not be running)
    "$venv_python" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null || true

    return 0
}

#
# start_daemon_safe() - Safely start the daemon
#
# Starts daemon without failing on errors.
# Useful when daemon might already be running.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#
# Returns:
#   Exit code 0 if started successfully or already running
#   Exit code 1 if start failed
#
start_daemon_safe() {
    local venv_python="$1"

    if [ -z "$venv_python" ]; then
        print_warning "start_daemon_safe: venv_python parameter required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    print_verbose "Starting daemon..."

    # Start daemon, suppress errors
    if "$venv_python" -m claude_code_hooks_daemon.daemon.cli start 2>/dev/null; then
        print_verbose "Daemon started"
        return 0
    else
        print_verbose "Daemon start returned error (may already be running)"
        return 0
    fi
}

#
# get_daemon_status() - Get daemon status information
#
# Captures full status output including any config validation errors.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#
# Returns:
#   Prints status output to stdout
#   Exit code from status command
#
get_daemon_status() {
    local venv_python="$1"

    if [ -z "$venv_python" ]; then
        echo "Error: venv_python parameter required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        echo "Error: Venv Python not found: $venv_python"
        return 1
    fi

    # Capture both stdout and stderr
    "$venv_python" -m claude_code_hooks_daemon.daemon.cli status 2>&1
}

#
# check_daemon_running() - Check if daemon is running
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#
# Returns:
#   Exit code 0 if daemon is running
#   Exit code 1 if daemon is not running or check failed
#
check_daemon_running() {
    local venv_python="$1"

    if [ -z "$venv_python" ]; then
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        return 1
    fi

    local status_output
    status_output=$(get_daemon_status "$venv_python")

    # Check for "Daemon: RUNNING" or "Status: RUNNING" (both formats used)
    if echo "$status_output" | grep -qE "(Daemon|Status): RUNNING"; then
        return 0
    else
        return 1
    fi
}

#
# restart_daemon_verified() - Restart daemon and verify it's running
#
# Performs full restart cycle with verification:
# 1. Stop daemon (safe)
# 2. Start daemon
# 3. Check status
# 4. Verify config validation passes
#
# This is the recommended high-level function for daemon restarts.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - verify_config (optional, default: true)
#        If true, checks for config validation in status output
#
# Returns:
#   Exit code 0 if daemon restarted and verified successfully
#   Exit code 1 if restart or verification failed
#
restart_daemon_verified() {
    local venv_python="$1"
    local verify_config="${2:-true}"

    if [ -z "$venv_python" ]; then
        print_error "restart_daemon_verified: venv_python parameter required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    print_info "Restarting daemon..."

    # Step 1: Stop daemon
    stop_daemon_safe "$venv_python"
    sleep 1

    # Step 2: Start daemon
    if ! start_daemon_safe "$venv_python"; then
        print_error "Failed to start daemon"
        return 1
    fi

    # Give daemon time to start
    sleep 2

    # Step 3: Get status
    print_verbose "Checking daemon status..."
    local status_output
    status_output=$(get_daemon_status "$venv_python")
    local status_exit_code=$?

    # Step 4: Verify running
    if ! echo "$status_output" | grep -qE "(Daemon|Status): RUNNING"; then
        print_error "Daemon is not running after restart"
        echo ""
        echo "Status output:"
        echo "$status_output"
        return 1
    fi

    print_success "Daemon is running"

    # Step 5: Check for config validation errors (if requested)
    if [ "$verify_config" = "true" ]; then
        if echo "$status_output" | grep -qi "config.*error\|validation.*failed\|invalid.*config"; then
            print_warning "Daemon started but config validation may have issues"
            echo ""
            echo "Status output:"
            echo "$status_output"
            return 1
        fi
    fi

    return 0
}

#
# wait_for_daemon_stop() - Wait for daemon to fully stop
#
# Polls daemon status until it's no longer running or timeout reached.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - timeout_seconds (optional, default: 10)
#
# Returns:
#   Exit code 0 if daemon stopped
#   Exit code 1 if timeout reached
#
wait_for_daemon_stop() {
    local venv_python="$1"
    local timeout_seconds="${2:-10}"

    if [ -z "$venv_python" ]; then
        return 1
    fi

    local elapsed=0
    while [ $elapsed -lt "$timeout_seconds" ]; do
        if ! check_daemon_running "$venv_python"; then
            return 0
        fi

        sleep 1
        elapsed=$((elapsed + 1))
    done

    print_warning "Daemon did not stop within ${timeout_seconds}s"
    return 1
}

#
# restart_daemon_quick() - Quick restart without verification
#
# Uses the daemon CLI restart command directly.
# Faster than stop+start but less control over errors.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#
# Returns:
#   Exit code from restart command
#
restart_daemon_quick() {
    local venv_python="$1"

    if [ -z "$venv_python" ]; then
        print_error "restart_daemon_quick: venv_python parameter required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    print_info "Restarting daemon (quick)..."

    if "$venv_python" -m claude_code_hooks_daemon.daemon.cli restart; then
        print_success "Daemon restarted"
        return 0
    else
        print_error "Daemon restart failed"
        return 1
    fi
}
