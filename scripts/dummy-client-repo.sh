#!/bin/bash
#
# dummy-client-repo.sh — provision a throwaway CLIENT-mode install for testing.
#
# WHY THIS EXISTS
# ---------------
# This repository dogfoods itself in SELF-INSTALL mode: source runs from
# /workspace/src, the venv lives at untracked/venv-*, and there is no
# .claude/hooks-daemon/scripts/ or .claude/skills/hooks-daemon/.
#
# A real client project is laid out completely differently: the daemon is a
# clone under .claude/hooks-daemon/, the venv lives under THAT directory, and
# the skill wrappers are deployed to .claude/skills/hooks-daemon/scripts/.
#
# Bugs therefore hide in the gap. Anything that resolves a path, an interpreter,
# a wrapper or a deployed asset can pass every self-install test and still be
# broken for every actual user. Verifying only in self-install mode is not
# verification.
#
# This script builds a genuine client-mode project at
# untracked/dummy-client-repo/ by driving the PRODUCTION installer
# (scripts/install_version.sh). It never synthesises install state: the
# v3.10.0 SEV-1 escaped precisely because a gate faked state instead of
# running the real chain, so faking it here would rebuild the same blind spot.
#
# USAGE
#   scripts/dummy-client-repo.sh create     # build fresh (destroys any existing)
#   scripts/dummy-client-repo.sh status     # show layout + daemon state
#   scripts/dummy-client-repo.sh cli ARGS   # run the daemon CLI inside it
#   scripts/dummy-client-repo.sh python     # print its resolved interpreter
#   scripts/dummy-client-repo.sh destroy    # stop daemon, remove worktree + dir
#
# The dummy daemon is isolated from the dogfood daemon by a dedicated HOSTNAME,
# so its socket/pid/log files never collide.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

DUMMY_ROOT="$REPO_ROOT/untracked/dummy-client-repo"
DUMMY_DAEMON_DIR="$DUMMY_ROOT/.claude/hooks-daemon"
INSTALL_VERSION_SH="$REPO_ROOT/scripts/install_version.sh"

# Dedicated hostname suffix — keeps daemon-{suffix}.{sock,pid,log} for the
# dummy install distinct from the dogfood daemon's runtime files.
DUMMY_HOSTNAME="dummy-client-repo"

# Placeholder remote: config validation checks only that origin EXISTS; the
# URL is never contacted, so this keeps provisioning network-free.
PLACEHOLDER_REMOTE="https://example.invalid/dummy-client.git"

info() { printf '  %s\n' "$*"; }
step() { printf '\n▶ %s\n' "$*"; }
fail() {
    printf '\n❌ %s\n' "$*" >&2
    exit 1
}

# --- helpers ---------------------------------------------------------------

# Resolve the venv interpreter the installer created inside the dummy daemon
# dir. Prints the path on stdout; returns non-zero when absent so callers can
# decide what to do (we never swallow that signal).
resolve_dummy_python() {
    local venv_dir
    for venv_dir in "$DUMMY_DAEMON_DIR"/untracked/venv-*; do
        if [ -x "$venv_dir/bin/python" ]; then
            printf '%s\n' "$venv_dir/bin/python"
            return 0
        fi
    done
    return 1
}

# Stop the dummy daemon if a working interpreter is present. Cleanup must not
# abort teardown, so a stop failure is reported and teardown continues — but it
# is never silenced.
stop_dummy_daemon() {
    local py
    if ! py="$(resolve_dummy_python)"; then
        info "no venv interpreter found — nothing to stop"
        return 0
    fi
    if HOSTNAME="$DUMMY_HOSTNAME" "$py" -m claude_code_hooks_daemon.daemon.cli stop; then
        info "dummy daemon stopped"
    else
        info "WARNING: dummy daemon stop reported an error (continuing teardown)"
    fi
}

remove_dummy_worktree() {
    if [ ! -e "$DUMMY_DAEMON_DIR" ]; then
        return 0
    fi
    if git -C "$REPO_ROOT" worktree remove --force "$DUMMY_DAEMON_DIR"; then
        info "worktree removed"
    else
        info "WARNING: git worktree remove failed; pruning and deleting directory"
        git -C "$REPO_ROOT" worktree prune
        rm -rf "$DUMMY_DAEMON_DIR"
    fi
}

# --- commands --------------------------------------------------------------

cmd_destroy() {
    step "Destroying dummy client repo"
    if [ ! -d "$DUMMY_ROOT" ]; then
        info "nothing to destroy ($DUMMY_ROOT does not exist)"
        return 0
    fi
    stop_dummy_daemon
    remove_dummy_worktree
    rm -rf "$DUMMY_ROOT"
    info "removed $DUMMY_ROOT"
}

cmd_create() {
    [ -f "$INSTALL_VERSION_SH" ] || fail "installer missing at $INSTALL_VERSION_SH"
    command -v uv > /dev/null || fail "uv is required to bootstrap the client venv"

    cmd_destroy

    step "Creating client-mode project skeleton"
    # install_version.sh Step 1 requires BOTH .claude/ and .git/ to already
    # exist at the project root — the installer populates their contents but
    # does not bootstrap the directories themselves. A real client has them
    # because install.sh runs from an existing git project.
    mkdir -p "$DUMMY_ROOT/.claude"
    git -C "$DUMMY_ROOT" init -q
    git -C "$DUMMY_ROOT" remote add origin "$PLACEHOLDER_REMOTE"
    info "git repo + .claude/ created at $DUMMY_ROOT"

    step "Cloning daemon into .claude/hooks-daemon (mirrors Layer 1 install)"
    # A detached worktree at HEAD gives the installer the exact tree under test
    # — including uncommitted-to-main work once committed — without a network
    # clone. ClientInstallValidator hard-codes this path.
    git -C "$REPO_ROOT" worktree add --detach "$DUMMY_DAEMON_DIR" HEAD
    info "worktree at $DUMMY_DAEMON_DIR"

    step "Running the PRODUCTION installer (scripts/install_version.sh)"
    # CI=true short-circuits ensure_venv into a no-op that yields an empty
    # capture and aborts the install; drop it so the real venv-bootstrap path
    # runs. NO_COLOR keeps installer output parseable.
    (
        cd "$DUMMY_ROOT"
        unset CI
        unset HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP
        NO_COLOR=1 HOSTNAME="$DUMMY_HOSTNAME" \
            bash "$INSTALL_VERSION_SH" "$DUMMY_ROOT" "$DUMMY_DAEMON_DIR"
    ) || fail "install_version.sh failed — the dummy client repo is NOT usable"

    step "Verifying the install produced a client-mode layout"
    local py
    py="$(resolve_dummy_python)" || fail "installer produced no venv under $DUMMY_DAEMON_DIR/untracked/"
    info "interpreter: $py"

    local wrapper="$DUMMY_ROOT/.claude/skills/hooks-daemon/scripts/daemon-cli.sh"
    if [ -f "$wrapper" ]; then
        info "skill wrapper deployed: $wrapper"
    else
        info "WARNING: skill wrapper NOT deployed at $wrapper"
    fi

    step "Verifying the daemon this install started is actually RUNNING"
    # FAIL FAST: an install that leaves no running daemon is not a usable
    # fixture, and silently handing one back would let a broken install path
    # masquerade as a passing provision. The CLI exits non-zero when the
    # daemon is down, so capture the code explicitly rather than discarding it.
    local status_output
    local status_rc=0
    status_output="$(cd "$DUMMY_ROOT" && HOSTNAME="$DUMMY_HOSTNAME" "$py" \
        -m claude_code_hooks_daemon.daemon.cli status)" || status_rc=$?
    if [ "$status_rc" -ne 0 ]; then
        printf '%s\n' "$status_output" >&2
        fail "daemon status query exited $status_rc — fixture unusable"
    fi
    if printf '%s' "$status_output" | grep -q 'RUNNING'; then
        info "daemon RUNNING"
    else
        printf '%s\n' "$status_output" >&2
        fail "install completed but the daemon is not RUNNING — fixture unusable"
    fi

    step "Dummy client repo ready"
    cmd_status
}

cmd_status() {
    if [ ! -d "$DUMMY_ROOT" ]; then
        info "not provisioned — run: scripts/dummy-client-repo.sh create"
        return 0
    fi
    info "root:        $DUMMY_ROOT"
    info "daemon dir:  $DUMMY_DAEMON_DIR"
    local py
    if py="$(resolve_dummy_python)"; then
        info "interpreter: $py"
        info "hostname:    $DUMMY_HOSTNAME"
        printf '\n'
        # cd is REQUIRED: the daemon CLI derives socket/pid/log paths from the
        # CWD's project root. Querying from the repo root resolves the
        # SELF-INSTALL paths instead and misreports the dummy daemon as down.
        cd "$DUMMY_ROOT"
        HOSTNAME="$DUMMY_HOSTNAME" "$py" -m claude_code_hooks_daemon.daemon.cli status
    else
        info "interpreter: NONE (install incomplete — re-run 'create')"
    fi
}

cmd_python() {
    local py
    py="$(resolve_dummy_python)" || fail "no dummy venv — run: scripts/dummy-client-repo.sh create"
    printf '%s\n' "$py"
}

cmd_cli() {
    local py
    py="$(resolve_dummy_python)" || fail "no dummy venv — run: scripts/dummy-client-repo.sh create"
    cd "$DUMMY_ROOT"
    HOSTNAME="$DUMMY_HOSTNAME" "$py" -m claude_code_hooks_daemon.daemon.cli "$@"
}

usage() {
    cat << 'EOF'
Usage: scripts/dummy-client-repo.sh <command> [args]

Commands:
  create      Build a fresh client-mode install at untracked/dummy-client-repo
              (destroys any existing one first). Drives the real installer.
  status      Show layout and dummy-daemon status.
  cli ARGS    Run the daemon CLI inside the dummy client repo.
  python      Print the dummy repo's resolved interpreter path.
  destroy     Stop the dummy daemon, remove the worktree and the directory.

Why: this repo runs in SELF-INSTALL mode, whose layout differs from every real
client install. Path/interpreter/wrapper/asset bugs pass self-install tests and
still break every user. Verify in BOTH modes.
EOF
}

main() {
    local command="${1:-}"
    if [ $# -gt 0 ]; then
        shift
    fi
    case "$command" in
        create) cmd_create ;;
        status) cmd_status ;;
        destroy) cmd_destroy ;;
        python) cmd_python ;;
        cli) cmd_cli "$@" ;;
        "" | -h | --help | help) usage ;;
        *)
            printf 'Unknown command: %s\n\n' "$command" >&2
            usage >&2
            exit 1
            ;;
    esac
}

main "$@"
