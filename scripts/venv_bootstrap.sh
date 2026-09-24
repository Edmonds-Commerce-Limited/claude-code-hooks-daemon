#!/bin/bash
#
# venv_bootstrap.sh - Build this project path's missing venv (Plan 00456).
#
# A daemon clone can be present with no venv for the current project path:
# the second view (host vs container) of one bind-mounted project shares the
# clone but not its per-path venv (Plan 00099, GitHub issue #53). This driver
# builds that venv with ensure_venv, under the same venv build lock every
# other builder takes (Plan 00100 Phase 4), and touches nothing else. In
# particular, other environments' untracked/venv-* are never modified.
#
# It runs from the clone, never from the project's copy of init.sh: the
# libraries and paths.py beside it are the clone's own.
#
# Usage:
#   venv_bootstrap.sh hook   <daemon_dir>
#       init.sh's venv-missing branch. NEVER blocks: evaluates the five
#       can_inline_bootstrap preconditions without a venv, and if they hold
#       starts the build DETACHED and returns. Hooks time out at 60s and a real
#       uv sync can take longer. Prints key=value lines for init.sh:
#         state=started|running|failed|refused|disabled|error
#         log=<path>          the build log (started, running, failed)
#         pid=<n>             the running build's process (running, once known)
#         elapsed=<seconds>   how long it has been running (running)
#         missing=<id>        one per failed precondition (refused)
#         fix=<id>: <text>    one per failed precondition (refused)
#         detail=<text>       what went wrong (error), or the setting that
#                             switched automatic builds off (disabled)
#       Exit 0 whatever the state; 2 on a usage error.
#
#   venv_bootstrap.sh repair <daemon_dir>
#       bin/hooks-daemon repair, before any venv exists. Builds in the
#       FOREGROUND (the CLI has no hook timeout), waiting for a build already
#       in progress rather than starting a second. Clears the failed-build
#       marker first. An explicit repair is a deliberate request, so it builds
#       even where HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 or CI=true switches the
#       automatic build off (and says so). Exit 0 once the venv resolves, 1
#       otherwise.
#
#   venv_bootstrap.sh build  <daemon_dir> <python> <fingerprint> <inputs>
#       The detached child `hook` starts. It inherits the lock through
#       HOOKS_DAEMON_VENV_LOCK_INHERITED. Not for direct use.
#
# State, all dot-prefixed under <daemon_dir>/untracked/ so no venv-* glob
# matches them, and keyed on the fingerprint the venv itself is named by, so
# one environment's failure never blocks another's build:
#   .venv-bootstrap-<fp>.log      the last build's output; its first lines name
#                                 the build's pid
#   .venv-bootstrap-<fp>.failed   present after a failed build: holds the
#                                 inputs signature it failed with
#   .venv-bootstrap.current       the record of the detached build holding the
#                                 lock now (venv.sh VENV_BUILD_RECORD_NAME)
#
# A detached build is bounded on every platform: HOOKS_DAEMON_VENV_BUILD_TIMEOUT
# seconds (900) from the hook that started it. At that point the child's own
# watchdog tells the child, which sends the build's process group TERM, then
# KILL after VENV_BUILD_KILL_GRACE_SECONDS. Only that is
# recorded as "timed out". Any other stop (a shutdown, someone ending the
# running state's pid) records nothing, so the next hook retries, and no stop
# is a failure when this path's venv resolves anyway.
#
# Retry policy: a failed build is NOT retried by the hook path until its
# inputs signature changes (pyproject.toml or uv.lock content, the chosen
# interpreter, or the uv binary: its path or its bytes; see
# paths.bootstrap_inputs_signature), or until `repair` clears the marker. A
# failure that changes no input (network down, disk full) waits for `repair`.
# The marker is judged while holding the lock, so a hook that raced a build
# failing cannot delete that fresh marker and retry.
#
# HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 or CI=true (the settings that make
# ensure_venv skip, venv.sh venv_bootstrap_switched_off_by) switch the hook
# path off: state=disabled, detail=<the setting>.
#

set -euo pipefail

_VB_SCRIPTS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_VB_PATHS_PY="${_VB_SCRIPTS_DIR%/*}/src/claude_code_hooks_daemon/daemon/paths.py"

# venv.sh sources output.sh (print_* all write to stderr, so stdout stays the
# key=value protocol) and puts ~/.local/bin, uv's default home, on PATH. The
# gate below therefore sees exactly the uv the build will use.
# shellcheck source=install/venv.sh
source "$_VB_SCRIPTS_DIR/install/venv.sh"
# shellcheck source=install/python_fingerprint.sh
source "$_VB_SCRIPTS_DIR/install/python_fingerprint.sh"
# shellcheck source=lib/python_discovery.sh
source "$_VB_SCRIPTS_DIR/lib/python_discovery.sh"
# shellcheck source=lib/resolve_venv.sh
source "$_VB_SCRIPTS_DIR/lib/resolve_venv.sh"

_VB_EX_USAGE=2
# The daemon's hard minimum; pyproject.toml's requires-python can only raise it.
_VB_MIN_PYTHON="3.11"

_vb_usage() {
    echo "usage: venv_bootstrap.sh hook|repair <daemon_dir>" >&2
    echo "       venv_bootstrap.sh build <daemon_dir> <python> <fingerprint> <inputs>" >&2
    exit "$_VB_EX_USAGE"
}

_vb_log_path() { echo "$1/untracked/.venv-bootstrap-$2.log"; }
_vb_marker_path() { echo "$1/untracked/.venv-bootstrap-$2.failed"; }
_vb_record_path() { echo "$1/untracked/$VENV_BUILD_RECORD_NAME"; }

#
# _vb_one_line() - Collapse text onto one line for the key=value protocol.
#
_vb_one_line() {
    local text="$1"
    text="${text//$'\n'/ }"
    echo "${text//$'\r'/ }"
}

#
# _vb_gate() - Evaluate the five preconditions with no venv (Plan 00456 T1.2).
#
# The interpreter is found by the same discovery helper every bash entry point
# uses, and it runs paths.py BY FILE PATH: paths.py is stdlib-only, so neither
# the package nor a venv is needed. When no compatible interpreter exists
# nothing can run the gate at all, and the one failed condition is reported
# with the discovery helper's own diagnostic as its fix.
#
# Sets VB_ALLOWED, VB_MISSING[], VB_FIXES[], VB_PYTHON, VB_FINGERPRINT,
# VB_INPUTS. Returns 1 with VB_ERROR set if the gate itself could not run.
#
_vb_gate() {
    local daemon_dir="$1"
    VB_ALLOWED="false"
    VB_MISSING=()
    VB_FIXES=()
    VB_PYTHON=""
    VB_FINGERPRINT=""
    VB_INPUTS=""
    VB_ERROR=""

    # On success the helper prints only the interpreter; on failure only its
    # diagnostic (stderr), so one capture carries whichever happened.
    local discovered
    if ! discovered="$(find_latest_python "$_VB_MIN_PYTHON" "$daemon_dir/pyproject.toml" 2>&1)"; then
        VB_MISSING=("compatible-python")
        VB_FIXES=("compatible-python: $(_vb_one_line "$discovered")")
        return 0
    fi

    local decision
    if ! decision="$("$discovered" "$_VB_PATHS_PY" bootstrap-decision --daemon-dir "$daemon_dir")"; then
        VB_ERROR="paths.py bootstrap-decision failed under $discovered (see the hook's stderr)"
        return 1
    fi

    local key value
    while IFS='=' read -r key value; do
        case "$key" in
            allowed) VB_ALLOWED="$value" ;;
            missing) VB_MISSING+=("$value") ;;
            fix) VB_FIXES+=("$value") ;;
            python) VB_PYTHON="$value" ;;
            fingerprint) VB_FINGERPRINT="$value" ;;
            inputs) VB_INPUTS="$value" ;;
        esac
    done <<< "$decision"
    return 0
}

#
# _vb_marker_inputs() - The inputs signature a failed-build marker recorded.
#
_vb_marker_inputs() {
    local marker="$1" key value
    while IFS='=' read -r key value; do
        if [ "$key" = "inputs" ]; then
            echo "$value"
            return 0
        fi
    done < "$marker"
    return 1
}

#
# _vb_write_marker() - Record a failed build (atomically: write, then rename).
#
_vb_write_marker() {
    local marker="$1" inputs="$2" exit_code="$3"
    local tmp="$marker.tmp.$$"
    printf 'inputs=%s\nfailed_at=%s\nexit=%s\n' \
        "$inputs" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$exit_code" > "$tmp"
    mv -f "$tmp" "$marker"
}

#
# _vb_clone_version() - The clone's own version, read without a venv.
#
_vb_clone_version() {
    local version_file="$1/src/claude_code_hooks_daemon/version.py"
    local version
    version="$(awk -F'"' '/^__version__[[:space:]]*=/ { print $2; exit }' "$version_file")"
    if [[ ! "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        print_error "venv bootstrap: cannot read a version from $version_file"
        return 1
    fi
    echo "$version"
}

#
# _vb_print_running() - state=running, naming the holder when it is a detached build.
#
# Another holder (an upgrade, a repair) keeps no record, so only the state is
# printed for it.
#
_vb_print_running() {
    local daemon_dir="$1" value started
    echo "state=running"
    if value="$(venv_build_record_field "$daemon_dir" log)"; then
        echo "log=$value"
    fi
    if value="$(venv_build_record_field "$daemon_dir" pid)"; then
        echo "pid=$value"
    fi
    if started="$(venv_build_record_field "$daemon_dir" started)" && [[ "$started" =~ ^[0-9]+$ ]]; then
        echo "elapsed=$(($(date +%s) - started))"
    fi
}

#
# _vb_build_under_lock() - Build with the lock held, then judge the result.
#
# Success is judged by the RESOLVER, not by ensure_venv's exit code: a venv
# whose metadata write failed is stamp-only, the resolver refuses it, and no
# hook could start the daemon from it. Records or clears the failed-build
# marker accordingly.
#
# Bootstrap switched off here is NOT a failed build: ensure_venv would skip
# and report success, so the build is refused up front and no marker is left.
#
# Returns 0 when the venv for this path now resolves, 1 when the build failed,
# 2 when bootstrap is switched off.
#
_vb_build_under_lock() {
    local daemon_dir="$1" python="$2" fingerprint="$3" inputs="$4"
    local marker version build_rc=0 resolved switched_off
    marker="$(_vb_marker_path "$daemon_dir" "$fingerprint")"

    if switched_off="$(venv_bootstrap_switched_off_by)"; then
        print_error "venv bootstrap: NOT building: $switched_off switches venv bootstrap off here. No failure is recorded."
        return 2
    fi

    if version="$(_vb_clone_version "$daemon_dir")"; then
        print_info "venv bootstrap: building the venv for $daemon_dir with $python (fingerprint $fingerprint)"
        if ! ensure_venv_locked "$daemon_dir" "v$version" "$python" > /dev/null; then
            build_rc=1
        fi
    else
        build_rc=1
    fi

    if [ "$build_rc" -eq 0 ] && resolved="$(resolve_venv_python "$daemon_dir")"; then
        rm -f "$marker"
        print_success "venv bootstrap SUCCEEDED: $resolved resolves for this path. The next hook starts the daemon."
        return 0
    fi

    _vb_write_marker "$marker" "$inputs" "$build_rc"
    print_error "venv bootstrap FAILED: no venv resolves for $daemon_dir after the build (ensure_venv exit $build_rc)."
    print_error "  Hooks will not retry until pyproject.toml, uv.lock, the Python interpreter or the uv binary changes."
    print_error "  After fixing the cause, retry in the foreground: $daemon_dir/bin/hooks-daemon repair"
    return 1
}

_vb_hook() {
    local daemon_dir="$1" switched_off

    if switched_off="$(venv_bootstrap_switched_off_by)"; then
        echo "state=disabled"
        echo "detail=$switched_off"
        return 0
    fi

    # Cheapest check first: while a build runs, every hook lands here and
    # should not pay for interpreter discovery on top.
    if venv_lock_is_held "$daemon_dir"; then
        _vb_print_running "$daemon_dir"
        return 0
    fi

    if ! _vb_gate "$daemon_dir"; then
        echo "state=error"
        echo "detail=$VB_ERROR"
        return 0
    fi

    local item
    if [ "$VB_ALLOWED" != "true" ]; then
        echo "state=refused"
        for item in ${VB_MISSING[@]+"${VB_MISSING[@]}"}; do
            echo "missing=$item"
        done
        for item in ${VB_FIXES[@]+"${VB_FIXES[@]}"}; do
            echo "fix=$item"
        done
        return 0
    fi

    local rc=0
    try_acquire_venv_lock "$daemon_dir" || rc=$?
    if [ "$rc" -eq "$VENV_LOCK_HELD" ]; then
        _vb_print_running "$daemon_dir"
        return 0
    fi
    if [ "$rc" -ne 0 ]; then
        echo "state=error"
        echo "detail=could not take the venv build lock under $daemon_dir/untracked (see the hook's stderr)"
        return 0
    fi

    # This process holds the lock, so it is the only starter, and the marker
    # is judged only now: a build that failed while this hook was on its way
    # here wrote its marker under the lock, and must not be retried.
    local log marker
    log="$(_vb_log_path "$daemon_dir" "$VB_FINGERPRINT")"
    marker="$(_vb_marker_path "$daemon_dir" "$VB_FINGERPRINT")"
    if [ -f "$marker" ] && [ "$(_vb_marker_inputs "$marker")" = "$VB_INPUTS" ]; then
        release_venv_lock
        echo "state=failed"
        echo "log=$log"
        return 0
    fi

    # A marker still here recorded different inputs: this build is the retry
    # it allows.
    rm -f "$marker"
    local bound
    bound="$(venv_build_timeout)"
    printf 'venv bootstrap started %s (python %s, daemon dir %s, bound %ss)\n' \
        "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$VB_PYTHON" "$daemon_dir" "$bound" > "$log"
    printf 'log=%s\nstarted=%s\nbound=%s\n' "$log" "$(date +%s)" "$bound" \
        > "$(_vb_record_path "$daemon_dir")"

    local spec
    spec="$(venv_lock_handoff_spec)"
    local -a detach=(nohup)
    if command -v setsid > /dev/null; then
        detach=(setsid)
    fi
    # Detached with every standard stream redirected, so the hook's stdout
    # pipe closes when this process exits and Claude Code does not wait on
    # the build. The child inherits the lock descriptor, and bounds its own
    # build (_vb_build), so the bound needs no `timeout` command.
    HOOKS_DAEMON_VENV_LOCK_INHERITED="$spec" "${detach[@]}" \
        bash "$_VB_SCRIPTS_DIR/venv_bootstrap.sh" \
        build "$daemon_dir" "$VB_PYTHON" "$VB_FINGERPRINT" "$VB_INPUTS" \
        < /dev/null >> "$log" 2>&1 &
    forget_venv_lock

    echo "state=started"
    echo "log=$log"
}

# The detached child's own identity, for its traps and its verdict on a stop.
_VB_CHILD_DAEMON_DIR=""
_VB_CHILD_LOG=""
_VB_CHILD_MARKER=""
_VB_CHILD_INPUTS=""
_VB_CHILD_STARTED=""
_VB_CHILD_BOUND=""
# Process groups: the build job, and the watchdog that bounds it.
_VB_CHILD_JOB=""
_VB_CHILD_WATCHDOG=""
# How often the watchdog checks that the build process is still there.
VENV_BUILD_WATCHDOG_POLL_SECONDS=1

#
# _vb_signal_group() - Send a signal to a whole process group, reporting a miss.
#
_vb_signal_group() {
    local sig="$1" pgid="$2" out
    if ! out="$(kill "-$sig" -- "-$pgid" 2>&1)"; then
        print_verbose "venv bootstrap: process group $pgid had already ended ($sig: $out)"
    fi
}

#
# _vb_job_running() - Is this job still running, by this shell's own job table?
#
# The job table is what proves a job's process group is still ours: its
# leader holds the group id while it runs, and once bash has seen it exit,
# that id is free for any new process to take.
#
_vb_job_running() {
    local pid
    for pid in $(jobs -rp); do
        [ "$pid" = "$1" ] && return 0
    done
    return 1
}

#
# _vb_signal_job() - Signal a job's process group, only while it is still ours.
#
_vb_signal_job() {
    if _vb_job_running "$2"; then
        _vb_signal_group "$1" "$2"
    fi
}

#
# _vb_stop_job() - TERM a job's process group, KILL it after the grace, reap it.
#
# Args: $1 the job's pid (its group id), $2 the grace in seconds.
# Returns the job's exit status.
#
_vb_stop_job() {
    local job="$1" grace="$2" waited=0 status=0
    _vb_signal_job TERM "$job"
    while _vb_job_running "$job" && [ "$waited" -lt "$grace" ]; do
        sleep 1
        waited=$((waited + 1))
    done
    _vb_signal_job KILL "$job"
    wait "$job" || status=$?
    return "$status"
}

#
# _vb_watchdog() - Tell the build process when its bound has passed.
#
# This is how the bound holds on every platform, with or without a `timeout`
# command (re-review N3). The lock heartbeat keeps a LIVE holder fresh, so
# without it a hung build would hold the lock for ever. The watchdog signals
# only the build process, and only just after confirming it is still there.
# The build process then stops its own job, because it alone knows whether it
# has reaped that job yet. A KILLed build process runs no trap: the watchdog
# sees it gone within one poll and exits having signalled nothing. By the
# bound, the build's process group id may belong to someone else (final
# review N7).
#
# Args: $1 the build process's pid, $2 the bound as an epoch deadline.
#
_vb_watchdog() {
    local owner="$1" deadline="$2" probe out
    while probe="$(kill -0 "$owner" 2>&1)"; do
        if [ "$(date +%s)" -ge "$deadline" ]; then
            print_warning "venv bootstrap: the build reached its ${_VB_CHILD_BOUND}s bound; stopping it"
            if ! out="$(kill -TERM "$owner" 2>&1)"; then
                print_verbose "venv bootstrap: the build process $owner ended first ($out)"
            fi
            return 0
        fi
        sleep "$VENV_BUILD_WATCHDOG_POLL_SECONDS"
    done
    print_verbose "venv bootstrap: the build process $owner is gone ($probe); the watchdog stops"
}

#
# _vb_judge_stop() - Say what a stopped build means, and record it only if it is a failure.
#
# A build job ends by signal either at its bound (the watchdog) or because
# something else stopped it: a shutdown, or someone ending the pid the running
# state names. Only the first is a timeout, and neither is a failure when this
# path's venv resolves anyway (re-review N2). A stop that is not a timeout
# records nothing, so the next hook retries.
#
# Args: $1 the stopped job's status. Returns 0 (the venv resolves), 124 (timed
# out, marker written) or 143 (stopped, nothing recorded).
#
_vb_judge_stop() {
    local status="$1" resolved elapsed
    if resolved="$(resolve_venv_python "$_VB_CHILD_DAEMON_DIR")"; then
        rm -f "$_VB_CHILD_MARKER"
        print_success "venv bootstrap: the build was stopped (status $status), but $resolved resolves for this path; nothing is recorded as failed."
        return 0
    fi
    elapsed=$(($(date +%s) - _VB_CHILD_STARTED))
    if [ "$elapsed" -ge "$_VB_CHILD_BOUND" ]; then
        _vb_write_marker "$_VB_CHILD_MARKER" "$_VB_CHILD_INPUTS" "timeout"
        print_error "venv bootstrap FAILED: the build timed out after ${_VB_CHILD_BOUND}s (HOOKS_DAEMON_VENV_BUILD_TIMEOUT) and was stopped."
        print_error "  Hooks will not retry it until its inputs change. Find out what hung, then retry in the foreground: $_VB_CHILD_DAEMON_DIR/bin/hooks-daemon repair"
        return 124
    fi
    print_warning "venv bootstrap: the build was stopped by a signal after ${elapsed}s, inside its ${_VB_CHILD_BOUND}s bound (a shutdown, or someone ending it)."
    print_warning "  Nothing is recorded as failed, so the next hook starts it again."
    return 143
}

#
# _vb_build_stop() - TERM/HUP/INT to the build process: stop the job, then judge.
#
_vb_build_stop() {
    trap - TERM HUP INT
    local status=143
    if [ -n "$_VB_CHILD_JOB" ]; then
        status=0
        _vb_stop_job "$_VB_CHILD_JOB" "$VENV_BUILD_KILL_GRACE_SECONDS" || status=$?
        _VB_CHILD_JOB=""
    fi
    local verdict=0
    _vb_judge_stop "$status" || verdict=$?
    exit "$verdict"
}

#
# _vb_build_exit() - Leave nothing running, release the lock, drop our record.
#
_vb_build_exit() {
    if [ -n "$_VB_CHILD_WATCHDOG" ]; then
        _vb_signal_job TERM "$_VB_CHILD_WATCHDOG"
    fi
    if [ -n "$_VB_CHILD_JOB" ]; then
        _vb_signal_job KILL "$_VB_CHILD_JOB"
    fi
    release_venv_lock
    local recorded
    if recorded="$(venv_build_record_field "$_VB_CHILD_DAEMON_DIR" log)" \
            && [ "$recorded" = "$_VB_CHILD_LOG" ]; then
        rm -f "$(_vb_record_path "$_VB_CHILD_DAEMON_DIR")"
    fi
}

_vb_build() {
    local daemon_dir="$1" python="$2" fingerprint="$3" inputs="$4"
    _VB_CHILD_DAEMON_DIR="$daemon_dir"
    _VB_CHILD_LOG="$(_vb_log_path "$daemon_dir" "$fingerprint")"
    _VB_CHILD_MARKER="$(_vb_marker_path "$daemon_dir" "$fingerprint")"
    _VB_CHILD_INPUTS="$inputs"

    adopt_venv_lock "$daemon_dir" || exit 1
    trap _vb_build_exit EXIT
    trap _vb_build_stop TERM HUP INT

    # The bound runs from when the hook started the build (its record).
    local now
    now="$(date +%s)"
    if ! _VB_CHILD_STARTED="$(venv_build_record_field "$daemon_dir" started)" \
            || [[ ! "$_VB_CHILD_STARTED" =~ ^[0-9]+$ ]]; then
        _VB_CHILD_STARTED="$now"
    fi
    if ! _VB_CHILD_BOUND="$(venv_build_record_field "$daemon_dir" bound)" \
            || [[ ! "$_VB_CHILD_BOUND" =~ ^[1-9][0-9]*$ ]]; then
        _VB_CHILD_BOUND="$(venv_build_timeout)"
    fi

    print_info "venv bootstrap: build pid $$, bound ${_VB_CHILD_BOUND}s"
    printf 'pid=%s\n' "$$" >> "$(_vb_record_path "$daemon_dir")"

    # Job control gives the build and the watchdog a process group each, so
    # a stop, or this process's exit, can end uv and everything it started,
    # never touching whatever group this process was started in.
    local status=0
    set -m
    _vb_build_under_lock "$daemon_dir" "$python" "$fingerprint" "$inputs" &
    _VB_CHILD_JOB="$!"
    _vb_watchdog "$$" $((_VB_CHILD_STARTED + _VB_CHILD_BOUND)) < /dev/null &
    _VB_CHILD_WATCHDOG="$!"
    set +m
    wait "$_VB_CHILD_JOB" || status=$?
    _VB_CHILD_JOB=""
    if [ "$status" -gt 128 ]; then
        _vb_judge_stop "$status" || status=$?
    fi
    return "$status"
}

_vb_repair() {
    local daemon_dir="$1" switched_off

    # The switch governs AUTOMATIC builds; asking for a repair is the
    # deliberate request it leaves open (review B1).
    if switched_off="$(venv_bootstrap_switched_off_by)"; then
        print_info "venv bootstrap: $switched_off switches AUTOMATIC venv builds off; an explicit repair builds anyway."
        unset HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP CI
    fi

    if ! _vb_gate "$daemon_dir"; then
        print_error "venv bootstrap: $VB_ERROR"
        return 1
    fi
    if [ "$VB_ALLOWED" != "true" ]; then
        print_error "Cannot build the venv for this project path. Nothing was changed. These conditions do not hold:"
        local fix
        for fix in ${VB_FIXES[@]+"${VB_FIXES[@]}"}; do
            print_error "  - $fix"
        done
        return 1
    fi

    # An explicit repair is the documented retry: forget the last failure.
    rm -f "$(_vb_marker_path "$daemon_dir" "$VB_FINGERPRINT")"

    print_info "No venv resolves for this project path. Building one in the foreground (waiting for any build already running)..."
    acquire_venv_lock "$daemon_dir" || return 1
    local rc=0
    _vb_build_under_lock "$daemon_dir" "$VB_PYTHON" "$VB_FINGERPRINT" "$VB_INPUTS" || rc=$?
    release_venv_lock
    return "$rc"
}

_vb_main() {
    local verb="${1:-}"
    local daemon_dir="${2:-}"
    case "$verb" in
        hook | repair)
            [ "$#" -eq 2 ] || _vb_usage
            ;;
        build)
            [ "$#" -eq 5 ] || _vb_usage
            ;;
        *)
            _vb_usage
            ;;
    esac
    if [ ! -d "$daemon_dir" ]; then
        echo "venv_bootstrap.sh: daemon dir does not exist: $daemon_dir" >&2
        exit "$_VB_EX_USAGE"
    fi
    daemon_dir="$(cd "$daemon_dir" && pwd)"

    case "$verb" in
        hook) _vb_hook "$daemon_dir" ;;
        repair) _vb_repair "$daemon_dir" ;;
        build) _vb_build "$daemon_dir" "$3" "$4" "$5" ;;
    esac
}

# Run only when executed; sourcing (tests of one function) defines and returns.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    _vb_main "$@"
fi
