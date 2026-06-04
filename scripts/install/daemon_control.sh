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
    # shellcheck source=output.sh
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

    # Stop daemon — daemon may not be running. `if` wrapper preserves
    # set -e safety while tolerating the expected "not running" exit code.
    if "$venv_python" -m claude_code_hooks_daemon.daemon.cli stop 2>/dev/null; then :; fi

    return 0
}

#
# start_daemon_safe() - Safely start the daemon
#
# Starts daemon and surfaces errors clearly. On failure, captures and
# prints the daemon's error output so users see actionable messages
# (e.g., "No git remote 'origin' configured").
#
# The starter's exit code and captured output are ALWAYS exposed via the
# globals DAEMON_START_EXIT_CODE and DAEMON_START_OUTPUT so callers that trust
# the daemon's actual RUNNING status over the starter's exit code (e.g.
# restart_daemon_verified, which must tolerate single-daemon enforcement
# SIGTERMing a superseded starter — exit 143) can defer the decision.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - quiet_on_failure (optional, default: false)
#        When "true", suppresses the hard-failure print so the caller can
#        decide whether the start truly failed (used by restart_daemon_verified
#        which consults the authoritative status poll instead).
#
# Returns:
#   Exit code 0 if started successfully
#   Exit code 1 if start failed
#
start_daemon_safe() {
    local venv_python="$1"
    local quiet_on_failure="${2:-false}"

    if [ -z "$venv_python" ]; then
        print_warning "start_daemon_safe: venv_python parameter required"
        return 1
    fi

    if [ ! -f "$venv_python" ]; then
        print_error "Venv Python not found: $venv_python"
        return 1
    fi

    print_verbose "Starting daemon..."
    print_info "Starting daemon (loading handlers, this may take a moment)..."

    # Capture daemon output so errors are visible (Bug 00088-2)
    local daemon_output
    local exit_code
    daemon_output=$("$venv_python" -m claude_code_hooks_daemon.daemon.cli start 2>&1) && exit_code=0 || exit_code=$?

    # Expose the starter result for callers that defer to the status poll.
    DAEMON_START_EXIT_CODE="$exit_code"
    DAEMON_START_OUTPUT="$daemon_output"

    if [ "$exit_code" -eq 0 ]; then
        print_verbose "Daemon started"
        return 0
    else
        if [ "$quiet_on_failure" != "true" ]; then
            print_error "Daemon failed to start (exit code $exit_code)"
            if [ -n "$daemon_output" ]; then
                echo ""
                echo "$daemon_output"
                echo ""
            fi
        fi
        return 1
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

    # Step 2: Start daemon — but do NOT treat the starter's exit code as
    # authoritative. Under single-daemon enforcement a concurrent start
    # (e.g. a live hook-triggered auto-start during an upgrade) can SIGTERM
    # this starter (exit 143) while still bringing a daemon up. The source of
    # truth for "did the daemon start" is the status poll below ("is a daemon
    # RUNNING and serving?"), so we run the starter in quiet mode, record its
    # result for diagnostics, and ALWAYS proceed to the poll.
    DAEMON_START_EXIT_CODE=0
    DAEMON_START_OUTPUT=""
    if start_daemon_safe "$venv_python" "true"; then :; fi
    local start_exit_code="${DAEMON_START_EXIT_CODE:-0}"
    local start_output="${DAEMON_START_OUTPUT:-}"

    # Step 3: Poll for daemon RUNNING status — up to 15s.
    # Plan 00100 Task 0.2: extended timeout (from implicit 2s) with
    # progress logging every 1s so the user sees activity on slow hosts.
    # Route polling stderr to a log file (errors expected during startup).
    local poll_err="/tmp/hooks-daemon-restart-poll.$$.err"
    local status_output=""
    local daemon_running=0
    local elapsed=0
    local timeout=15
    while [ "$elapsed" -lt "$timeout" ]; do
        status_output=$(get_daemon_status "$venv_python" 2>>"$poll_err")
        if echo "$status_output" | grep -qE "(Daemon|Status): RUNNING"; then
            daemon_running=1
            break
        fi
        print_verbose "waiting for daemon (${elapsed}/15s)"
        sleep 1
        elapsed=$((elapsed + 1))
    done

    # Step 4: pgrep fallback — if status poll timed out but the daemon
    # process exists, retry status for another 5s before declaring failure.
    if [ "$daemon_running" -eq 0 ]; then
        if pgrep -f "claude-hooks-daemon\|claude_code_hooks_daemon" > /dev/null; then
            print_verbose "daemon process exists but not yet responsive — retrying status check for 5 more seconds"
            local retry_elapsed=0
            while [ "$retry_elapsed" -lt 5 ]; do
                status_output=$(get_daemon_status "$venv_python" 2>>"$poll_err")
                if echo "$status_output" | grep -qE "(Daemon|Status): RUNNING"; then
                    daemon_running=1
                    break
                fi
                sleep 1
                retry_elapsed=$((retry_elapsed + 1))
            done
        fi
    fi

    # Clean up polling stderr log (contents logged only if failure below).
    if [ "$daemon_running" -eq 0 ]; then
        print_error "Daemon is not running after restart"
        # Surface the starter diagnostics ONLY now that the authoritative poll
        # has confirmed no daemon is running — a non-zero starter exit on its
        # own (e.g. 143 from enforcement supersession) is not a failure.
        if [ "$start_exit_code" -ne 0 ]; then
            print_error "Daemon start command exited with code ${start_exit_code}"
            if [ -n "$start_output" ]; then
                echo ""
                echo "$start_output"
                echo ""
            fi
        fi
        echo ""
        echo "Status output:"
        echo "$status_output"
        if [ -s "$poll_err" ]; then
            echo ""
            echo "Polling stderr:"
            cat "$poll_err"
        fi
        rm -f "$poll_err"
        return 1
    fi
    rm -f "$poll_err"

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
