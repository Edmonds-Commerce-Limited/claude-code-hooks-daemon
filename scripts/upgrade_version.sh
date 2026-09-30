#!/bin/bash
#
# upgrade_version.sh - Layer 2: Version-specific upgrade orchestrator
#
# This script is called by the Layer 1 upgrade.sh after determining the
# target version. It implements "Upgrade = Clean Reinstall + Config
# Preservation" using modular library functions from scripts/install/.
#
# CRITICAL: This script must NEVER run in self-install mode.
#
# Usage (called by Layer 1):
#   bash scripts/upgrade_version.sh "$PROJECT_ROOT" "$DAEMON_DIR" "$TARGET_VERSION"
#
# Arguments:
#   $1 - PROJECT_ROOT: Absolute path to the user's project root
#   $2 - DAEMON_DIR: Absolute path to the daemon installation directory
#   $3 - TARGET_VERSION: Git tag or ref to upgrade to (e.g., v2.6.0)
#
# Exit codes:
#   0 - Upgrade completed successfully
#   1 - Upgrade failed (rollback attempted)
#

set -euo pipefail

# Plan 00376 fresh review BLOCKER 1: a function exported into the environment
# (BASH_FUNC_*) would shadow the very tools the pre-deploy gate relies on, and
# this script defines every function it runs itself.
while read -r _ _ _imported_function; do
    unset -f "$_imported_function"
done < <(declare -F)

# Resolve script directory for sourcing library modules
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_LIB_DIR="$SCRIPT_DIR/install"

# Plan 00376 review2 MAJOR 1: sanitise the inherited environment before any
# other library is sourced. A hostile BASH_ENV/ENV that already ran at THIS
# shell's own startup cannot be undone, but resetting it here stops it (and
# every other steering variable) from reaching a single subshell or child
# process any library sourced below goes on to spawn. See
# install/env_sanitise.sh for the full rationale per variable family.
# shellcheck source=install/env_sanitise.sh
source "$INSTALL_LIB_DIR/env_sanitise.sh"
_sanitise_layer2_env

# Source all library modules
# shellcheck source=install/output.sh
source "$INSTALL_LIB_DIR/output.sh"
# shellcheck source=install/mode_guard.sh
source "$INSTALL_LIB_DIR/mode_guard.sh"
# shellcheck source=install/prerequisites.sh
source "$INSTALL_LIB_DIR/prerequisites.sh"
# shellcheck source=install/project_detection.sh
source "$INSTALL_LIB_DIR/project_detection.sh"
# shellcheck source=install/venv.sh
source "$INSTALL_LIB_DIR/venv.sh"
# shellcheck source=install/python_fingerprint.sh
source "$INSTALL_LIB_DIR/python_fingerprint.sh"
# shellcheck source=install/venv_resolver.sh
source "$INSTALL_LIB_DIR/venv_resolver.sh"
# shellcheck source=install/hooks_deploy.sh
source "$INSTALL_LIB_DIR/hooks_deploy.sh"
# shellcheck source=install/gitignore.sh
source "$INSTALL_LIB_DIR/gitignore.sh"
# shellcheck source=install/slash_commands.sh
source "$INSTALL_LIB_DIR/slash_commands.sh"
# shellcheck source=install/validation.sh
source "$INSTALL_LIB_DIR/validation.sh"
# shellcheck source=install/daemon_control.sh
source "$INSTALL_LIB_DIR/daemon_control.sh"
# shellcheck source=install/rollback.sh
source "$INSTALL_LIB_DIR/rollback.sh"
# shellcheck source=install/settings_deploy.sh
source "$INSTALL_LIB_DIR/settings_deploy.sh"
# shellcheck source=install/config_preserve.sh
source "$INSTALL_LIB_DIR/config_preserve.sh"
# shellcheck source=install/upgrade_transition.sh
source "$INSTALL_LIB_DIR/upgrade_transition.sh"
# shellcheck source=install/branch_install.sh
source "$INSTALL_LIB_DIR/branch_install.sh"
# shellcheck source=lib/python_discovery.sh
source "$SCRIPT_DIR/lib/python_discovery.sh"

# Plan 00376 review4 MAJOR 2: a library may change PATH when it is sourced
# (venv.sh prepends $HOME/.local/bin for the install scripts), so the trusted
# PATH is set again once the last one has loaded. Every step before the gate
# runs its tools from here; uv is reached by name through _venv_uv.
PATH="$(_gate_trusted_path)"
export PATH

# ============================================================
# Argument parsing
# ============================================================

PROJECT_ROOT="${1:-}"
DAEMON_DIR="${2:-}"
TARGET_VERSION="${3:-}"

if [ -z "$PROJECT_ROOT" ] || [ -z "$DAEMON_DIR" ] || [ -z "$TARGET_VERSION" ]; then
    fail_fast "Usage: upgrade_version.sh <PROJECT_ROOT> <DAEMON_DIR> <TARGET_VERSION>"
fi

if [ ! -d "$PROJECT_ROOT" ]; then
    fail_fast "Project root does not exist: $PROJECT_ROOT"
fi

if [ ! -d "$DAEMON_DIR" ]; then
    fail_fast "Daemon directory does not exist: $DAEMON_DIR"
fi

# Run AT the project root. The daemon-control helpers invoke daemon.cli
# start/stop/status with no --project-root, and the CLI resolves the project
# it manages from the current working directory -- so an upgrade driven from
# anywhere else started and "verified" a daemon for the caller's own project,
# wrote its socket and PID file there, and reported success for a client it
# never touched (Plan 00291 canary re-run). Both arguments are made absolute
# first so a relative DAEMON_DIR keeps pointing at the same directory.
PROJECT_ROOT="$(cd "$PROJECT_ROOT" && pwd)"
DAEMON_DIR="$(cd "$DAEMON_DIR" && pwd)"
cd "$PROJECT_ROOT"

# Plan 00291: the guarded branch-install gate (see install/branch_install.sh).
# Evaluated here, before anything is touched: a half-armed gate is refused
# outright. When armed, INSTALL_STAMP becomes vX.Y.Z+<ref>.<sha> for the
# commit actually checked out, and that stamp -- not TARGET_VERSION -- is
# what the venv records and what status / version_check read back.
BRANCH_INSTALL_STATE="$(branch_install_gate_state)" || fail_fast "Refusing the half-armed branch-install gate (see above)"
TRACK_REF="${HOOKS_DAEMON_UNSAFE_TRACK_REF:-}"
TRACK_REASON="${HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE:-}"
INSTALL_STAMP="$TARGET_VERSION"

# _resolve_install_stamp() - Set INSTALL_STAMP for the commit HEAD is on.
#
# Called once the daemon dir sits on the target (the fast path finds it there
# already; the slow path arrives after Step 6). A release install keeps the
# tag as its stamp; a branch install computes and announces its own.
_resolve_install_stamp() {
    if [ "$BRANCH_INSTALL_STATE" != "armed" ]; then
        INSTALL_STAMP="$TARGET_VERSION"
        return 0
    fi
    INSTALL_STAMP="$(branch_install_stamp "$DAEMON_DIR" "$TRACK_REF")" \
        || fail_fast "Could not derive the branch-install stamp for $DAEMON_DIR"
    print_branch_install_banner "$TRACK_REF" "$TRACK_REASON" "$INSTALL_STAMP"
}

# Plan 00376 review MAJOR 4: the handoff from Layer 1. Layer 1 writes a
# one-shot file in a private temp dir it created, holding its own PID and the
# commit it moved the daemon dir from, and passes the PATH. It counts only if
# this script's parent wrote it, as this user, and it is deleted on reading:
# an exported or inherited HOOKS_DAEMON_UPGRADE_HANDOFF names a file some
# other process wrote, and is ignored. Only a valid handoff makes the flags in
# UPGRADE_FLAGS and the handed-over ref count.
UPGRADE_CALLER="direct"
HANDOFF_PREVIOUS_REF=""

# _read_handoff() - Validate and consume Layer 1's handoff file. Returns 1
# when there is none or it is not genuine.
_read_handoff() {
    local path="${HOOKS_DAEMON_UPGRADE_HANDOFF:-}"
    unset HOOKS_DAEMON_UPGRADE_HANDOFF
    if [ -z "$path" ]; then
        return 1
    fi
    if [ -L "$path" ] || [ ! -f "$path" ] || [ ! -O "$path" ] || [ ! -O "$(dirname "$path")" ]; then
        print_warning "Ignoring the upgrade handoff $path: it is not a file this user created in a directory this user owns."
        return 1
    fi
    local writer_pid="" previous_ref=""
    if ! read -r writer_pid previous_ref < "$path"; then
        print_warning "Ignoring the upgrade handoff $path: it could not be read."
        rm -f -- "$path"
        return 1
    fi
    rm -f -- "$path"
    if [ "$writer_pid" != "$PPID" ]; then
        print_warning "Ignoring the upgrade handoff $path: process $writer_pid wrote it, not this script's caller ($PPID)."
        return 1
    fi
    HANDOFF_PREVIOUS_REF="$previous_ref"
    return 0
}

if _read_handoff; then
    UPGRADE_CALLER="layer1"
elif [ -n "${HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION:-}" ] && [ -z "${HOOKS_DAEMON_UPGRADE_SECOND_PASS:-}" ]; then
    # A Layer 1 that hands the previous version over but no handoff file
    # predates the gate: it cannot pass the acknowledgement, and it reports
    # success whatever this script exits with (review MAJOR 2).
    UPGRADE_CALLER="pre-gate-layer1"
fi

# The caller confirms it has read the gate's listing with
# --skip-reading-confirmation=<digest>, the digest the stop printed. A bare
# flag is passed on as an empty acknowledgement, which matches no listing.
# Nothing else confirms it: there is deliberately no "no terminal, so nobody
# to ask" inference.
READING_ACKNOWLEDGED=false
READING_ACKNOWLEDGEMENT=""

# _take_acknowledgement() - Record the acknowledgement among the given words.
_take_acknowledgement() {
    local word
    for word in "$@"; do
        case "$word" in
            --skip-reading-confirmation=*)
                READING_ACKNOWLEDGED=true
                READING_ACKNOWLEDGEMENT="${word#*=}"
                ;;
            --skip-reading-confirmation)
                READING_ACKNOWLEDGED=true
                READING_ACKNOWLEDGEMENT=""
                ;;
        esac
    done
}

_take_acknowledgement "${@:4}"
if [ "$UPGRADE_CALLER" = "layer1" ] && [ -n "${UPGRADE_FLAGS:-}" ]; then
    read -r -a _LAYER1_FLAGS <<< "$UPGRADE_FLAGS"
    if [ "${#_LAYER1_FLAGS[@]}" -gt 0 ]; then
        _take_acknowledgement "${_LAYER1_FLAGS[@]}"
    fi
fi

# The uv that builds the venv, named for this run with `--uv <path>` (or
# `--uv=<path>`) among the trailing arguments: Layer 1 passes it on as an
# argument, never in the environment, and the second pass forwards it with the
# rest of "${@:4}". It must be an absolute path to an executable file. No
# environment variable or config key names it, so what builds the venv is what
# the human typed for this run.
_take_uv_override() {
    local uv_path=""
    while [ $# -gt 0 ]; do
        case "$1" in
            --uv=*)
                uv_path="${1#*=}"
                ;;
            --uv)
                [ $# -ge 2 ] || fail_fast "--uv requires a path argument"
                uv_path="$2"
                shift
                ;;
            *)
                shift
                continue
                ;;
        esac
        shift
        case "$uv_path" in
            /*) ;;
            *) fail_fast "--uv $uv_path is not an absolute path to an executable file" ;;
        esac
        if [ ! -f "$uv_path" ] || [ ! -x "$uv_path" ]; then
            fail_fast "--uv $uv_path is not an absolute path to an executable file"
        fi
        VENV_UV_OVERRIDE="$uv_path"
    done
}

_take_uv_override "${@:4}"

# The gate's stop codes (install/upgrade_gate.py GateVerdict.exit_code).
GATE_NEEDS_ACKNOWLEDGEMENT=3
GATE_NEEDS_APPROVAL=4
# A gate that has not decided in this long has hung (a pathological Detect
# pattern on a long line): the timeout is a crash, so it stops the upgrade.
GATE_TIMEOUT_SECONDS=300
GATE_TIMED_OUT=124
# GATE_SAFE_PATH, _gate_dir_is_trusted(), _gate_trusted_path() and
# _gate_tool() are defined in install/env_sanitise.sh, sourced before any
# other library above -- _sanitise_layer2_env() needs the trusted path to
# reset PATH at entry, and Layer 1 (upgrade.sh) needs _gate_tool to resolve
# the `bash` it launches Layer 2 with from the same trusted locations, so
# those four moved there rather than staying here. Every function below that
# decides or feeds the gate resolves its tools from `_gate_trusted_path`, the
# entries of GATE_SAFE_PATH that `_gate_dir_is_trusted` accepts, never the
# raw GATE_SAFE_PATH variable directly.

# The owner's approval the gate accepted; removed once the upgrade completes,
# so a failure after the gate does not spend it.
APPROVAL_MARKER_USED=""

# _installed_release_from_docs() - The release .claude/HOOKS-DAEMON.md was
# generated by, or nothing: the version this project last deployed.
_installed_release_from_docs() {
    local PATH
    PATH="$(_gate_trusted_path)"
    local doc="$PROJECT_ROOT/.claude/HOOKS-DAEMON.md"
    if [ ! -f "$doc" ]; then
        return 0
    fi
    awk 'match($0, /Generated on [^(]*\(v[0-9]+\.[0-9]+\.[0-9]+\)/) { s = substr($0, RSTART, RLENGTH); sub(/.*\(v/, "", s); sub(/\)$/, "", s); print s; exit }' "$doc"
}

# _restore_target() - Print the ref of the version this project has INSTALLED,
# or nothing when it cannot be told.
#
# The venv stamp first (a branch stamp ends in its commit, a release stamp is
# its tag), then the release HOOKS-DAEMON.md names, then the ref a genuine
# Layer 1 moved the dir from. Never the checkout's own HEAD: on a fresh clone,
# a manual checkout or a re-run it already sits on the target.
_restore_target() {
    local PATH
    PATH="$(_gate_trusted_path)"
    local candidate="" release=""
    if [[ "$INSTALLED_VERSION" == *+* ]]; then
        candidate="${INSTALLED_VERSION##*.}"
    elif [ -n "$INSTALLED_VERSION" ]; then
        candidate="v${INSTALLED_VERSION#v}"
    else
        release="$(_installed_release_from_docs)"
        if [ -n "$release" ]; then
            candidate="v$release"
        fi
    fi
    if [ -n "$candidate" ] && git -C "$DAEMON_DIR" rev-parse --verify --quiet "${candidate}^{commit}" > /dev/null; then
        echo "$candidate"
        return 0
    fi
    if [ -n "$HANDOFF_PREVIOUS_REF" ] && git -C "$DAEMON_DIR" rev-parse --verify --quiet "${HANDOFF_PREVIOUS_REF}^{commit}" > /dev/null; then
        echo "$HANDOFF_PREVIOUS_REF"
    fi
}

# _warn_about_a_pre_gate_layer1() - Say what a pre-gate Layer 1 cannot.
_warn_about_a_pre_gate_layer1() {
    if [ "$UPGRADE_CALLER" != "pre-gate-layer1" ]; then
        return 0
    fi
    print_warning "THE UPGRADE DID NOT COMPLETE. The upgrade.sh that called this script predates the pre-deploy gate: it will report success (exit 0) although nothing was deployed, and it cannot pass --skip-reading-confirmation."
    print_warning "Run $TARGET_VERSION's own upgrade.sh instead (it knows the gate):"
    echo "  tmp=\"\$(mktemp)\" && git -C \"$DAEMON_DIR\" show \"$TARGET_VERSION:scripts/upgrade.sh\" > \"\$tmp\" && bash \"\$tmp\" --project-root \"$PROJECT_ROOT\" $TARGET_VERSION"
}

# abort_before_deploy() - Stop the upgrade with nothing deployed (Plan 00376
# Tasks 1.2 and 3.3). Args: exit code, reason. Always exits non-zero.
#
# The daemon dir goes back to the version this project has INSTALLED
# (_restore_target) rather than staying on the target, on every route, so the
# next run meets the same gate and the old venv never runs new source. Before
# the gate nothing else has changed -- it runs before ensure_venv -- so the
# restore is the whole undo. A direct call's slow path is already covered by
# the snapshot rollback in the EXIT trap, so there it only has to exit.
abort_before_deploy() {
    local PATH
    PATH="$(_gate_trusted_path)"
    local exit_code="$1"
    local reason="$2"
    if [ "$UPGRADE_STARTED" = true ]; then
        print_error "Upgrade $reason. Rolling back to the pre-upgrade state; nothing new was deployed."
        exit "$exit_code"
    fi
    local restore_ref
    restore_ref="$(_restore_target)"
    if [ -z "$restore_ref" ]; then
        print_error "Upgrade $reason. Nothing was deployed into $PROJECT_ROOT and the venv was not touched, but the version this project had installed cannot be told (no venv stamp, no version in .claude/HOOKS-DAEMON.md), so the daemon dir is still on $TARGET_VERSION. Put it back on the release you had installed before anything else runs: git -C \"$DAEMON_DIR\" reset --hard <that release's tag>"
        _warn_about_a_pre_gate_layer1
        exit "$exit_code"
    fi
    if [ "$(git -C "$DAEMON_DIR" rev-parse "${restore_ref}^{commit}")" = "$(git -C "$DAEMON_DIR" rev-parse HEAD)" ]; then
        print_info "The daemon dir is on the installed version ($restore_ref)."
    elif git -C "$DAEMON_DIR" reset --hard --quiet "$restore_ref"; then
        print_success "Daemon dir restored to the installed version ($restore_ref)."
    else
        print_error "Upgrade $reason, and the daemon dir could not be restored to $restore_ref (git's error is above). It is still on $TARGET_VERSION with nothing deployed; restore it with: git -C \"$DAEMON_DIR\" reset --hard $restore_ref"
        _warn_about_a_pre_gate_layer1
        exit 1
    fi
    print_error "Upgrade $reason. Nothing was deployed into $PROJECT_ROOT; the installed daemon starts again on the next hook event."
    _warn_about_a_pre_gate_layer1
    exit "$exit_code"
}

# consume_used_approval() - Remove the owner's approval once the upgrade it
# let through has completed (one approval, one upgrade).
consume_used_approval() {
    if [ -z "$APPROVAL_MARKER_USED" ]; then
        return 0
    fi
    rm -f -- "$APPROVAL_MARKER_USED"
    print_info "The owner's approval was used by this upgrade and removed ($APPROVAL_MARKER_USED)."
}

# _target_release() - Print the release the checked-out target carries.
#
# The release part of INSTALL_STAMP: the tag, or for a branch install the
# pyproject version its stamp starts with. A direct call naming a commit no tag
# describes has a sha for a stamp, so the checkout's own version.py answers
# instead; "unknown" if even that is unreadable, which the gate treats as a
# range it cannot read.
_target_release() {
    local PATH
    PATH="$(_gate_trusted_path)"
    local release="${INSTALL_STAMP%%+*}"
    if [[ "$release" =~ ^[vV]?[0-9]+(\.[0-9]+)*$ ]]; then
        echo "$release"
        return 0
    fi
    release="$(awk -F'"' '/^__version__[[:space:]]*=/ { print $2; exit }' \
        "$DAEMON_DIR/src/claude_code_hooks_daemon/version.py")"
    echo "${release:-unknown}"
}

# The oldest Python the standalone gate runs on (datetime.UTC).
GATE_PYTHON_FLOOR="3.11"
GATE_PYTHON=""

# _pick_gate_python() - Set GATE_PYTHON to a Python found only in a trusted
# GATE_SAFE_PATH location (review2 MAJOR 2: root-owned, not group- or
# world-writable); returns 1 when there is none.
#
# Never HOOKS_DAEMON_PYTHON, never the caller's PATH, and never the installed
# venv: that venv lives in the project, where an agent can write, and a `.pth`
# in its site-packages runs inside the gate's own process even under -I. The
# override still chooses the interpreter the target's venv is built with.
_pick_gate_python() {
    local PATH
    PATH="$(_gate_trusted_path)"
    GATE_PYTHON="$(unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH; find_latest_python "$GATE_PYTHON_FLOOR" "$DAEMON_DIR/pyproject.toml")" || GATE_PYTHON=""
    [ -n "$GATE_PYTHON" ]
}

# run_pre_deploy_phase() - The pre-deploy gate (Plan 00376 Tasks 1.1, 3.1-3.3).
#
# Runs once the daemon dir sits on the target and BEFORE ensure_venv rebuilds
# the venv for it, on every route: Layer 1 checks the target out before it
# calls this script, so it arrives on the idempotent path; a direct call
# arrives after Step 6. Earlier, the pre-checkout tree holds no guide for the
# version being installed; later, the venv is already the target's and a stop
# could no longer leave the install as it was.
#
# install/upgrade_gate.py prints the reading list, every pre-upgrade task
# detected in the project, and any reason the change needs the owner; then it
# decides (see its module docstring). It runs through the stdlib-only
# standalone entry because the target's venv does not exist yet. A stop goes
# through abort_before_deploy. A gate that crashes also stops the upgrade: an
# undecided gate must not wave an upgrade through.
#
# The FROM side is what is INSTALLED, never the checkout (review MAJOR 1): the
# gate reads the venv stamp passed here, else .claude/HOOKS-DAEMON.md, and
# with neither it treats the range as unknown and sends it to the owner. The
# TARGET side is the release part of INSTALL_STAMP, which for a branch install
# is the pyproject version the branch carries. When the venv already carries
# the target's exact stamp -- a re-run, or a direct call's second pass after
# the first restamped it -- the gate has nothing new to say and proceeds.
# There is no environment switch that skips it.
#
# Nothing the caller's environment chooses runs it or speaks for it (fresh
# review BLOCKER 1): it runs under `env -i` with GATE_SAFE_PATH, through the
# timeout and Python found there, and it writes its verdict, headed by a
# nonce drawn here, into a directory created here. A zero exit counts only with
# that file: a stdout line is what any wrapper process can print.
run_pre_deploy_phase() {
    local PATH
    PATH="$(_gate_trusted_path)"
    local target_semver
    target_semver="$(_target_release)"
    local gate_script="$DAEMON_DIR/src/claude_code_hooks_daemon/install/upgrade_gate_standalone.py"
    local undecided="stopped: the pre-deploy gate could not run, and an undecided gate does not let an upgrade through"
    if ! _pick_gate_python; then
        print_error "No Python $GATE_PYTHON_FLOOR+ interpreter for the pre-deploy gate in a system location ($GATE_SAFE_PATH). The gate never runs on an interpreter an environment variable, the caller's PATH or the project's own venv names; the user installs a Python $GATE_PYTHON_FLOOR+ in one of those locations (or links one there)."
        abort_before_deploy 1 "$undecided"
    fi
    local env_bin="" od_bin="" timeout_bin=""
    if ! env_bin="$(_gate_tool env)" || ! od_bin="$(_gate_tool od)"; then
        print_error "The pre-deploy gate needs env and od from a system location ($GATE_SAFE_PATH)."
        abort_before_deploy 1 "$undecided"
    fi
    local nonce="" verdict_dir=""
    nonce="$("$od_bin" -An -N16 -tx1 /dev/urandom)" || nonce=""
    nonce="${nonce//[[:space:]]/}"
    # -p /tmp: review2 MINOR 1. A bare `mktemp -d` honours an inherited
    # TMPDIR, which the upgrade guard denies only on the SAME command as the
    # upgrade -- an earlier `export TMPDIR=...` is not that. Fixing the
    # directory here removes the inherited value from this decision.
    if [ -z "$nonce" ] || ! verdict_dir="$(mktemp -d -p /tmp)"; then
        print_error "Could not set up the pre-deploy gate's verdict file (no /dev/urandom, or mktemp failed)."
        abort_before_deploy 1 "$undecided"
    fi
    local verdict_file="$verdict_dir/verdict"
    local -a gate_args=(
        --daemon-dir "$DAEMON_DIR"
        --project-root "$PROJECT_ROOT"
        --installed-stamp "$INSTALLED_VERSION"
        --to "$target_semver"
        --target-stamp "$INSTALL_STAMP"
        --target-ref "$TARGET_VERSION"
    )
    if [ "$BRANCH_INSTALL_STATE" = "armed" ]; then
        gate_args+=(--include-unreleased)
    fi
    if [ "$READING_ACKNOWLEDGED" = true ]; then
        gate_args+=(--acknowledgement "$READING_ACKNOWLEDGEMENT")
    fi

    gate_args+=(--verdict-file "$verdict_file" --nonce "$nonce")

    # env -i: no caller variable reaches the gate (no PATH, PYTHON*, GIT_*,
    # LD_* or exported function). -I -S: no site module, so no site-packages
    # and no `.pth` code; the gate is stdlib-only.
    local -a runner=("$env_bin" -i "PATH=$GATE_SAFE_PATH" "LANG=C.UTF-8")
    if [ -n "${HOME:-}" ]; then
        runner+=("HOME=$HOME")
    fi
    if timeout_bin="$(_gate_tool timeout)"; then
        runner+=("$timeout_bin" "$GATE_TIMEOUT_SECONDS")
    else
        print_warning "No timeout command in a system location, so the gate runs without a time limit."
    fi
    print_info "Pre-deploy gate: what upgrading to $target_semver changes (run by $GATE_PYTHON)..."
    local gate_exit=0
    "${runner[@]}" "$GATE_PYTHON" -I -S "$gate_script" "${gate_args[@]}" || gate_exit=$?

    # A zero exit counts only with the verdict file the gate wrote, headed by
    # this run's nonce: anything that exits 0 having decided nothing does not
    # wave the upgrade through.
    local nonce_line="" line="" verdict=""
    if [ -f "$verdict_file" ] && [ ! -L "$verdict_file" ] && [ -O "$verdict_file" ]; then
        {
            IFS= read -r nonce_line || nonce_line=""
            while IFS= read -r line; do
                case "$line" in
                    verdict=*) verdict="${line#verdict=}" ;;
                    approval-marker=*) APPROVAL_MARKER_USED="${line#approval-marker=}" ;;
                esac
            done
        } < "$verdict_file"
    fi
    rm -rf -- "$verdict_dir"
    if [ "$gate_exit" -eq 0 ] && { [ "$nonce_line" != "nonce=$nonce" ] || [ "$verdict" != "proceed" ]; }; then
        print_error "The pre-deploy gate exited 0 without writing this run's verdict; $GATE_PYTHON did not run the gate."
        APPROVAL_MARKER_USED=""
        gate_exit=1
    fi
    case "$gate_exit" in
        0) ;;
        "$GATE_NEEDS_ACKNOWLEDGEMENT" | "$GATE_NEEDS_APPROVAL")
            abort_before_deploy "$gate_exit" "stopped by the pre-deploy gate (see above)"
            ;;
        "$GATE_TIMED_OUT")
            print_error "The pre-deploy gate did not decide within ${GATE_TIMEOUT_SECONDS}s."
            abort_before_deploy 1 "stopped: the pre-deploy gate could not decide, and an undecided gate does not let an upgrade through"
            ;;
        *)
            print_error "The pre-deploy gate itself failed (exit $gate_exit) - its error is above."
            abort_before_deploy 1 "stopped: the pre-deploy gate could not decide, and an undecided gate does not let an upgrade through"
            ;;
    esac
}

# run_config_compatibility_check() - Report whether the project's config names
# handlers the target removed or renamed (Plan 00376 Task 1.1). Needs the
# target's venv, so it runs after verify_venv and before the first deploy.
# Report only: the handler names it flags are fixed in the config afterwards.
#
# Every value reaches Python as an ARGV entry, never spliced into its source.
run_config_compatibility_check() {
    if [ -n "${HOOKS_DAEMON_COMPAT_CHECK_DONE:-}" ]; then
        return 0
    fi
    if [ "$CURRENT_VERSION" = "unknown" ]; then
        print_info "Previous version unknown: skipping the config compatibility check"
        return 0
    fi

    local target_semver
    target_semver="$(_target_release)"
    local compat_exit=0
    if [ -f "$TARGET_CONFIG" ]; then
        print_info "Checking config compatibility with target version..."
        "$VENV_PYTHON" - "$DAEMON_DIR" "$TARGET_CONFIG" "$CURRENT_VERSION" "$target_semver" \
            <<'COMPAT_CHECK_PY' || compat_exit=$?
import sys
from pathlib import Path

import yaml

from claude_code_hooks_daemon.install.upgrade_compatibility import CompatibilityChecker

daemon_dir = Path(sys.argv[1])
target_config = Path(sys.argv[2])
current_version = sys.argv[3]
target_version = sys.argv[4]

changelog_path = daemon_dir / "CHANGELOG.md"
if not changelog_path.exists():
    print("WARNING: CHANGELOG.md not found, skipping compatibility check", file=sys.stderr)
    sys.exit(0)

with target_config.open() as handle:
    user_config = yaml.safe_load(handle)

checker = CompatibilityChecker(
    changelog_path=changelog_path,
    current_version=current_version,
    target_version=target_version,
)
report = checker.check_compatibility(user_config)

if report.is_compatible:
    print("✓ All handlers compatible with target version", file=sys.stderr)
else:
    print(checker.generate_user_friendly_report(report), file=sys.stderr)
    print(
        f"Your config references handlers that are incompatible with {target_version}. "
        "The upgrade continues; fix these in .claude/hooks-daemon.yaml once it completes.",
        file=sys.stderr,
    )
COMPAT_CHECK_PY
        if [ "$compat_exit" -ne 0 ]; then
            print_error "Config compatibility check crashed (exit $compat_exit) - traceback above."
            print_warning "Continuing without a compatibility verdict; review $TARGET_CONFIG after the upgrade."
        fi
    fi

    export HOOKS_DAEMON_COMPAT_CHECK_DONE=1
}

# Derived paths
# v3.7.0+ venvs are fingerprint-keyed; v3.8.1 added a scan-fallback for the
# fingerprint-mismatch case (installer used python3.13, resolver's python3
# is 3.9). The shared helper implements the same precedence as
# src/.../skills/hooks-daemon/scripts/_resolve-venv.sh so install-time and
# skill-time resolvers always agree. ensure_venv rebuilds/refreshes below.
#
# Plan 00104 Task 5.2: tolerate the no-existing-venv case so set -e does
# not abort the upgrade on a fresh clone or v2.x-stamp project (no
# .daemon-metadata.json, no fingerprint venv yet). Step 7 (ensure_venv)
# bootstraps the new venv from $HOOKS_DAEMON_PYTHON / python3. Stderr is
# NOT silenced — any genuine failure from the canonical resolver
# (paths.py SSOT missing, daemon_dir invalid, paths.py crash) is surfaced
# to the operator. The downstream `[ -f "$VENV_PYTHON" ]` guards already
# gate the codepaths that require an existing interpreter.
VENV_PYTHON="$(resolve_existing_venv_python "$DAEMON_DIR")" || VENV_PYTHON=""
if [ -z "$VENV_PYTHON" ]; then
    print_info "No existing venv found — Step 7 will bootstrap a fresh one via ensure_venv."
fi

# Plan 00164 Phase 1: the TRUE "from" version for user-facing messaging is the
# EXISTING venv's `.daemon-version` stamp — the version the venv was actually
# built/verified against — read BEFORE ensure_venv rebuilds it. Layer 1 has
# already checked out the target tag, so the git ref / pyproject version can be
# AHEAD of what the venv was really built from (the reported "git at v3.40.0 but
# venv stamped v3.38.0" case). Empty when there is no existing stamped venv
# (fresh install / pre-stamp build) — the transition helpers treat empty as
# "installing".
#
# Plan 00376: that venv is resolved with HOOKS_DAEMON_PYTHON and
# HOOKS_DAEMON_VENV_PATH unset. Both are operator overrides for which
# interpreter runs the daemon, but either could name a "venv" whose stamp
# already says the target, and the pre-deploy gate takes that stamp as the
# installed version. VENV_PYTHON above keeps honouring them for daemon control.
# The answer counts only when it is one of THIS daemon dir's own fingerprint
# venvs (untracked/venv-*), compared as physical paths: defence in depth over
# the resolver's own cache rule (Plan 00466 N37). Resolved with GATE_SAFE_PATH,
# like everything else that feeds the gate.
INSTALLED_VERSION=""

# _read_installed_version() - Set INSTALLED_VERSION.
_read_installed_version() {
    local PATH
    PATH="$(_gate_trusted_path)"
    local venv_python="" venv_real="" venv_dir=""
    venv_python="$(unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH; resolve_existing_venv_python "$DAEMON_DIR")" || venv_python=""
    if [ -z "$venv_python" ]; then
        return 0
    fi
    venv_dir="$(dirname "$(dirname "$venv_python")")"
    venv_real="$(cd "$venv_dir" && pwd -P)" || venv_real=""
    case "$venv_real" in
        "$(cd "$DAEMON_DIR" && pwd -P)"/untracked/venv-*) ;;
        *)
            print_warning "Not reading the installed version from $venv_python: it is not one of $DAEMON_DIR's own venvs."
            return 0
            ;;
    esac
    INSTALLED_VERSION="$(get_venv_version "$venv_dir")"
}
_read_installed_version

EXAMPLE_CONFIG="$DAEMON_DIR/.claude/hooks-daemon.yaml.example"
SETTINGS_JSON_SOURCE="$DAEMON_DIR/.claude/settings.json"
TARGET_CONFIG="$PROJECT_ROOT/.claude/hooks-daemon.yaml"

# Rollback state
SNAPSHOT_ID=""
ROLLBACK_REF=""
UPGRADE_STARTED=false

# Self-replacement detection.
#
# Step 6 checks out the target version INTO THE DIRECTORY THIS SCRIPT LIVES IN.
# Bash has already read the program it is running, so every step after that
# checkout still comes from the version being REPLACED: a step the new release
# adds is not skipped by a gate, it is absent from the running program, and the
# operator sees a clean successful upgrade that quietly did less than the
# release notes promised.
#
# Layer 1 (upgrade.sh) does not have this problem — it checks out first and
# then invokes this script as a fresh process. But this script remains a
# public entry point that older skill shims and existing runbooks still call
# directly, so it has to detect the swap itself. `cksum` is used rather than a
# sha tool because it is POSIX and present everywhere this script runs.
LAYER2_TARGET_SCRIPT="$DAEMON_DIR/scripts/upgrade_version.sh"
LAYER2_SOURCE_FINGERPRINT_BEFORE=""
if [ -f "$LAYER2_TARGET_SCRIPT" ]; then
    LAYER2_SOURCE_FINGERPRINT_BEFORE="$(cksum < "$LAYER2_TARGET_SCRIPT")"
fi
LAYER2_SOURCE_CHANGED=false

# ============================================================
# Rollback trap
# ============================================================

# shellcheck disable=SC2317  # Invoked indirectly by EXIT trap
cleanup_on_failure() {
    local exit_code=$?

    # Unconditional, and from HERE rather than from Step 10: the baseline is a
    # temp copy Step 5 made, and a positional `rm` after the merge only runs
    # when the script gets that far. Every early exit in between leaked one.
    # cleanup_old_default_config declines a path it did not create, so this is
    # safe on the Layer 1 path where the baseline belongs to the caller.
    cleanup_old_default_config "${OLD_DEFAULT_CONFIG:-}"

    if [ "$exit_code" -ne 0 ] && [ "$UPGRADE_STARTED" = true ]; then
        echo ""
        print_warning "Upgrade failed - attempting rollback..."

        # Restore from snapshot if available
        if [ -n "$SNAPSHOT_ID" ]; then
            if restore_state_snapshot "$PROJECT_ROOT" "$DAEMON_DIR" "$SNAPSHOT_ID" "normal"; then
                print_success "Rolled back to pre-upgrade state (snapshot: $SNAPSHOT_ID)"
            else
                print_error "Rollback failed. Manual intervention required."
                print_info "Snapshot ID: $SNAPSHOT_ID"
                print_info "Snapshots: $(get_snapshot_dir "$DAEMON_DIR")"
            fi
        elif [ -n "$ROLLBACK_REF" ]; then
            # Fallback: just checkout the old ref
            if git -C "$DAEMON_DIR" checkout "$ROLLBACK_REF" 2>/dev/null; then
                print_success "Rolled back git to: $ROLLBACK_REF"
            else
                print_error "Git rollback failed. Previous ref: $ROLLBACK_REF"
            fi
        fi

        # Try to restart daemon with old code
        if [ -f "$VENV_PYTHON" ]; then
            print_info "Attempting to restart daemon with previous version..."
            # Best-effort rollback — we're already inside cleanup_on_failure, so
            # we cannot abort the trap if restart also fails. `if` wrapper
            # preserves set -e safety while tolerating the failure.
            if restart_daemon_quick "$VENV_PYTHON" 2>/dev/null; then :; fi
        fi
    fi
}
trap cleanup_on_failure EXIT

# ============================================================
# Step 1: Safety checks
# ============================================================

print_header "Claude Code Hooks Daemon - Upgrade"

print_info "Project root: $PROJECT_ROOT"
print_info "Daemon directory: $DAEMON_DIR"
print_info "Target version: $TARGET_VERSION"

log_step "1" "Safety checks"

# CRITICAL: Abort if running in self-install mode. detect_self_install_mode
# asks about the PROJECT root (self-install IS the project checkout), not
# the daemon directory beneath it -- pass PROJECT_ROOT, the argument that
# question is actually about (Plan 00455).
ensure_normal_mode_only "$PROJECT_ROOT"

# Validate project structure
validate_project_structure "$PROJECT_ROOT" "true"

# Validate the daemon dir is the ROOT of its own git repository.
#
# `[ -d "$DAEMON_DIR/.git" ]` was safe but too narrow, and Layer 1
# (scripts/upgrade.sh) already replaced it for exactly this reason — the fix
# landed in one script and not its sibling. A git WORKTREE or SUBMODULE stores
# .git as a FILE and is a perfectly valid repository, so the directory test
# false-rejects both. That is not theoretical: it is why
# scripts/dummy-client-repo.sh, this project's own client-mode harness, could
# not exercise this script at all — leaving the Layer 2 upgrade path untested
# in client mode, which is precisely where field bugs come from.
#
# `rev-parse --show-prefix` prints the queried directory's path RELATIVE to its
# repo toplevel, so it is empty exactly AT the toplevel. It accepts clones,
# worktrees and submodules, and still rejects the dangerous shape: a plain
# .claude/hooks-daemon/ inside the user's own repo, where git walks UP and
# answers about the PARENT.
#
# Deliberately NOT a `--show-toplevel` string comparison: that mis-fires
# whenever symlinks make two spellings of the same path differ.
# Pinned by tests/integration/test_upgrade_sh_daemon_dir_detection.py.
DAEMON_DIR_PREFIX="$(git -C "$DAEMON_DIR" rev-parse --show-prefix 2>/dev/null)" \
    || fail_fast "Daemon directory is not a git repository: $DAEMON_DIR"
if [ -n "$DAEMON_DIR_PREFIX" ]; then
    fail_fast "Daemon directory is not the root of its own git repository: $DAEMON_DIR (it sits ${DAEMON_DIR_PREFIX%/} inside a repository rooted above it, so upgrading here would modify THAT repository). Reinstall the daemon into $DAEMON_DIR."
fi

# ============================================================
# Step 2: Pre-upgrade checks
# ============================================================

log_step "2" "Pre-upgrade checks"

# Get current version info.
#
# On a second pass (see the re-exec at the end of this script) the checkout has
# already moved to the target, so reading version.py here would report the NEW
# version as the one being upgraded FROM. The first pass hands the real
# starting version over instead, keeping the summary honest.
#
# Plan 00291 Task 1.3: with no venv (the fresh-clone client state) there is
# no interpreter to ask, but version.py is a one-line file, so read it
# directly rather than reporting "unknown" for a checkout that plainly says.
# Layer 1 hands the true pre-checkout version over in the environment, which
# takes precedence because on its path the checkout has already moved.
CURRENT_VERSION="unknown"
VERSION_FILE="$DAEMON_DIR/src/claude_code_hooks_daemon/version.py"
if [ -n "${HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION:-}" ]; then
    CURRENT_VERSION="$HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION"
elif [ -f "$VERSION_FILE" ] && [ -f "$VENV_PYTHON" ]; then
    CURRENT_VERSION=$("$VENV_PYTHON" -c "
from claude_code_hooks_daemon.version import __version__
print(__version__)
" 2>/dev/null || echo "unknown")
elif [ -f "$VERSION_FILE" ]; then
    CURRENT_VERSION=$(awk -F'"' '/^__version__[[:space:]]*=/ { print $2; exit }' "$VERSION_FILE")
    if [ -z "$CURRENT_VERSION" ]; then
        CURRENT_VERSION="unknown"
    fi
fi

# Get current git ref for rollback
ROLLBACK_REF=$(git -C "$DAEMON_DIR" describe --tags --exact-match 2>/dev/null || \
               git -C "$DAEMON_DIR" rev-parse --short HEAD 2>/dev/null || \
               echo "")

print_info "Current version: $CURRENT_VERSION"
print_info "Current git ref: ${ROLLBACK_REF:-unknown}"

# Idempotent deployment path.
#
# Plan 00164 Phase 1: Layer 1 (upgrade.sh) ALWAYS checks out the target tag
# before invoking this script, so `ROLLBACK_REF` (git describe --exact-match)
# always equals `$TARGET_VERSION` here — this branch is the effective single
# deployment path for every client upgrade. The message therefore must describe
# the TRUE transition of the actually-built venv (INSTALLED_VERSION, the venv
# stamp) → target, NOT the always-equal git ref. This is the fix for the
# misleading "Already at version X" that fired even on a genuine version jump.
#
# Plan 00291: "already at the target" is a question about COMMITS, not about
# the spelling of a name. Layer 1 hands a branch install its resolved commit
# as the target, which no tag describes, so the name comparison alone would
# send every branch install down the slow path while every tag takes this
# one. A second tag on the same commit is the same case for a release.
TARGET_COMMIT="$(git -C "$DAEMON_DIR" rev-parse --verify --quiet "${TARGET_VERSION}^{commit}")" || TARGET_COMMIT=""
HEAD_COMMIT="$(git -C "$DAEMON_DIR" rev-parse HEAD)"
if [ "$ROLLBACK_REF" = "$TARGET_VERSION" ] || { [ -n "$TARGET_COMMIT" ] && [ "$TARGET_COMMIT" = "$HEAD_COMMIT" ]; }; then
    _resolve_install_stamp
    print_success "$(upgrade_transition_headline "$INSTALLED_VERSION" "$INSTALL_STAMP")"
    print_info "Running idempotent deployment steps to ensure files are current..."

    # Every Layer 1 upgrade arrives here with the target checked out: the gate
    # runs now, before ensure_venv touches anything, so a stop leaves only the
    # checkout to restore.
    run_pre_deploy_phase

    # Plan 00099: ensure_venv uses a fingerprint-keyed venv path so concurrent
    # environments (container vs host, different Pythons) don't clobber each
    # other. Handles stale/missing stamps internally (recreate+restamp).
    VENV_PATH=$(ensure_venv "$DAEMON_DIR" "$INSTALL_STAMP" "${HOOKS_DAEMON_PYTHON:-python3}")
    if [ -z "$VENV_PATH" ]; then
        fail_fast "ensure_venv returned empty path"
    fi
    VENV_PYTHON="$VENV_PATH/bin/python"

    if ! verify_venv "$VENV_PYTHON" "$DAEMON_DIR"; then
        fail_fast "Virtual environment verification failed"
    fi

    # The target's own compatibility check needs its venv, and runs before the
    # first deploy.
    run_config_compatibility_check

    # Plan 00099: clean up pre-v3.7.0 legacy venv on idempotent re-runs too.
    # The full upgrade path (Step 7) already does this, but multi-host projects
    # hit the fast path on every host after the first upgrade — so the legacy
    # venv lingered until manually removed. Match the slow-path cleanup exactly.
    LEGACY_VENV="$DAEMON_DIR/untracked/venv"
    if [ -d "$LEGACY_VENV" ] && [ "$VENV_PATH" != "$LEGACY_VENV" ]; then
        print_info "Removing legacy pre-v3.7.0 venv at $LEGACY_VENV"
        rm -rf "$LEGACY_VENV"
    fi

    deploy_all_hooks "$PROJECT_ROOT" "$DAEMON_DIR" "normal" "$VENV_PYTHON"

    # No snapshot exists on this branch — it exits before Step 3 — so the
    # helper takes its own backup. Previously this copy was silent AND
    # uncovered, on the path the comment above calls the effective single
    # deployment path for every client upgrade (Plan 00176 Task 2.0).
    deploy_settings_json_checked "$SETTINGS_JSON_SOURCE" "$PROJECT_ROOT/.claude/settings.json" "" \
        "$VENV_PYTHON" "${HOOKS_DAEMON_OLD_DEFAULT_SETTINGS:-}" \
        || fail_fast "Could not preserve the existing settings.json"

    setup_all_gitignores "$PROJECT_ROOT" "$DAEMON_DIR" "normal" || print_warning ".gitignore setup had warnings (non-fatal)"

    deploy_slash_commands "$PROJECT_ROOT" "$DAEMON_DIR" "normal"

    # Values reach Python as ARGV entries and are never spliced into the
    # generated source. A path containing a quote would otherwise close the
    # Python string literal and raise SyntaxError instead of deploying.
    "$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" <<'REDEPLOY_SKILLS_PY'
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.skills import deploy_skills

daemon_source = Path(sys.argv[1])
project_root = Path(sys.argv[2])

try:
    deploy_skills(daemon_source, project_root)
    print("✓ Skills redeployed to .claude/skills/hooks-daemon/")
except Exception as e:
    print(f"✗ Skill redeployment failed: {e}")
    sys.exit(1)
REDEPLOY_SKILLS_PY

    # Plan 00136: deploy plan workflow (config-driven SSoT) on the idempotent
    # fast path too, so already-at-target re-runs also deliver mkplan.bash.
    if "$VENV_PYTHON" - "$PROJECT_ROOT" "$TARGET_CONFIG" <<'FASTPATH_PLAN_WORKFLOW_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.plan_workflow import deploy_plan_workflow_if_enabled

result = deploy_plan_workflow_if_enabled(Path(sys.argv[1]), Path(sys.argv[2]))
for msg in result.messages:
    print(f"  -> {msg}")
FASTPATH_PLAN_WORKFLOW_PY
        print_success "Plan workflow deployment complete"
    else
        print_warning "Plan workflow deployment had issues (non-fatal)"
    fi

    # Plan 00334: refresh the daemon-owned core documents on the fast path too.
    # This is the path that carries an upstream correction to an install set up
    # long ago, so skipping it here would freeze every already-at-target client
    # on the documents they were first seeded with.
    if "$VENV_PYTHON" - "$PROJECT_ROOT" "$TARGET_CONFIG" <<'FASTPATH_CORE_DOCS_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.core_docs import deploy_core_docs_if_enabled

result = deploy_core_docs_if_enabled(Path(sys.argv[1]), Path(sys.argv[2]))
for msg in result.messages:
    print(f"  -> {msg}")
FASTPATH_CORE_DOCS_PY
        print_success "Core document deployment complete"
    else
        print_warning "Core document deployment had issues (non-fatal)"
    fi

    # Plan 00147/00148: refresh AND arm the ccy supervisor on the idempotent fast
    # path too, so already-at-target re-runs deliver the current claude-supervise.py
    # and ensure ccy.env exports CCY_CLAUDE_WRAPPER (an existing wrapper is kept).
    if "$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" "$TARGET_CONFIG" <<'FASTPATH_CCY_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.ccy_supervisor import deploy_ccy_supervisor_if_enabled

result = deploy_ccy_supervisor_if_enabled(
    Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
)
for msg in result.messages:
    print(f"  -> {msg}")
if result.recommend_enable:
    print("  -> TIP: set ccy.deploy_supervisor: true in .claude/hooks-daemon.yaml to keep this on")
FASTPATH_CCY_PY
        print_success "ccy supervisor deployment complete"
    else
        print_warning "ccy supervisor deployment had issues (non-fatal)"
    fi

    # Plan 00290 Phase 5: relay binary provisioning on the idempotent fast
    # path too, so a re-run against the same target version still honours a
    # newly-set daemon.transport.relay_source. Null (the default) is a no-op.
    if "$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" "$TARGET_VERSION" <<'FASTPATH_RELAY_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.forwarder_generator import load_transport_config
from claude_code_hooks_daemon.install.relay_deploy import deploy_relay_if_configured

daemon_dir = Path(sys.argv[1])
project_root = Path(sys.argv[2])
version_tag = sys.argv[3]

transport = load_transport_config(project_root)
result = deploy_relay_if_configured(daemon_dir, project_root, transport, version_tag=version_tag)
for msg in result.messages:
    print(f"  -> {msg}")
sys.exit(0 if (transport.relay_source is None or result.deployed) else 1)
FASTPATH_RELAY_PY
        print_success "Relay binary provisioning complete"
    else
        print_warning "Relay binary provisioning had issues (non-fatal; relay rung falls back to the legacy transport)"
    fi

    if ! restart_daemon_verified "$VENV_PYTHON"; then
        fail_fast "Daemon failed to start after idempotent upgrade"
    fi

    if ! run_post_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false"; then
        fail_fast "Post-install verification failed after idempotent upgrade"
    fi

    # Plan 00336 Phase 3: regenerate .claude/HOOKS-DAEMON.md. The restart above
    # already refreshed the CLAUDE.md <hooksdaemon> block (DaemonController
    # .initialise runs the ClaudeMdInjector), but nothing regenerated this
    # document, so it kept describing the version the project was INSTALLED at.
    # Runs AFTER the restart so it reflects the handler set that actually
    # loaded, and only warns on failure — guidance is not worth aborting a
    # completed upgrade for.
    if "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli generate-docs --project-root "$PROJECT_ROOT"; then
        print_success "Regenerated .claude/HOOKS-DAEMON.md"
    else
        print_warning "Failed to regenerate handler docs (non-fatal; run 'hooks-daemon regenerate-docs')"
    fi

    consume_used_approval
    print_success "$(upgrade_transition_summary "$INSTALLED_VERSION" "$INSTALL_STAMP")"
    if [ "$BRANCH_INSTALL_STATE" = "armed" ]; then
        print_branch_install_banner "$TRACK_REF" "$TRACK_REASON" "$INSTALL_STAMP"
    fi
    exit 0
fi

# Run pre-upgrade safety checks if venv exists
if [ -f "$VENV_PYTHON" ]; then
    # fail_on_error=false: a non-zero return is the documented "problems were
    # found and printed" signal, and is non-fatal here by design.
    if ! run_pre_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false"; then
        print_warning "Pre-install checks reported problems (non-fatal, see above)"
    fi
fi

# The gate and the config compatibility check are NOT run here: this tree is
# still the version being replaced on a direct call, so neither the target's
# guides nor its handlers exist yet. run_pre_deploy_phase and
# run_config_compatibility_check run once the target is checked out.

# ============================================================
# Step 3: Create state snapshot
# ============================================================

log_step "3" "Creating state snapshot for rollback"

SNAPSHOT_ID=$(create_state_snapshot "$PROJECT_ROOT" "$DAEMON_DIR" "normal" 2>/dev/null | tail -1)

if [ -n "$SNAPSHOT_ID" ]; then
    print_success "Snapshot created: $SNAPSHOT_ID"
else
    print_warning "Could not create snapshot - upgrade will proceed without rollback capability"
fi

# Mark upgrade as started (enables rollback on failure)
UPGRADE_STARTED=true

# ============================================================
# Step 4: Stop daemon
# ============================================================

log_step "4" "Stopping daemon"
# A fresh-clone client (config and forwarders present, no venv yet) has no
# daemon to stop. VENV_PYTHON is deliberately empty there, and
# stop_daemon_safe treats an empty argument as a caller error (exit 1), which
# under set -e is a rollback — so the stop is skipped explicitly, out loud.
if [ -n "$VENV_PYTHON" ]; then
    stop_daemon_safe "$VENV_PYTHON"
    sleep 1
else
    print_info "No existing venv, so no daemon to stop — skipping daemon stop"
fi

# ============================================================
# Step 5: Backup and extract config customizations
# ============================================================

log_step "5" "Preserving config customizations"

# Resolve the diff baseline: the default config shipped by the version being
# upgraded FROM. Invoked via Layer 1 the checkout has already happened, so
# $EXAMPLE_CONFIG here is the NEW default and the real baseline arrives in
# HOOKS_DAEMON_OLD_DEFAULT_CONFIG; invoked directly, Step 5 still pre-dates
# Step 6 and the on-disk example is correct. resolve_old_default_config picks
# whichever applies -- see its contract in install/config_preserve.sh.
OLD_DEFAULT_CONFIG=$(resolve_old_default_config "$EXAMPLE_CONFIG")

# Backup current config
CONFIG_BACKUP=""
if [ -f "$TARGET_CONFIG" ]; then
    CONFIG_BACKUP=$(backup_config "$PROJECT_ROOT")
    print_verbose "Config backup: $CONFIG_BACKUP"
fi

# Breaking changes detection (compare old vs new default config)
if [ -f "$TARGET_CONFIG" ] && [ -f "$OLD_DEFAULT_CONFIG" ] && [ -f "$VENV_PYTHON" ]; then
    print_info "Analyzing config for breaking changes..."

    # Run config diff analyzer.
    #
    # Capture its STDOUT only: stdout is the JSON payload, stderr is
    # diagnostics. The previous `2>&1` folded the two together, so a single
    # warning line corrupted the JSON — and the `|| echo "{}"` fallback then
    # hid that corruption behind an empty result indistinguishable from a
    # clean "no breaking changes" run. Failures are now reported explicitly.
    DIFF_EXIT=0
    DIFF_RESULT=$("$SCRIPT_DIR/install/config_diff_analyzer.sh" \
        "$TARGET_CONFIG" "$OLD_DEFAULT_CONFIG") || DIFF_EXIT=$?

    if [ "$DIFF_EXIT" -ne 0 ]; then
        print_error "config_diff_analyzer.sh failed (exit $DIFF_EXIT) - its stderr is above."
        print_warning "Skipping breaking-changes detection; review $TARGET_CONFIG after the upgrade."
    elif [ -z "$DIFF_RESULT" ]; then
        print_error "config_diff_analyzer.sh produced no output - expected a JSON object on stdout."
        print_warning "Skipping breaking-changes detection; review $TARGET_CONFIG after the upgrade."
    else
        # The diff JSON and the daemon dir arrive as ARGV entries, never
        # spliced into the generated Python source: a value containing a quote
        # used to produce a SyntaxError that the old blanket suppression at the
        # end of this block then swallowed whole.
        BREAKING_CHANGES_EXIT=0
        "$VENV_PYTHON" - "$DAEMON_DIR" "$DIFF_RESULT" <<'BREAKING_CHANGES_PY' || BREAKING_CHANGES_EXIT=$?
import json
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.breaking_changes_detector import BreakingChangesDetector

daemon_dir = Path(sys.argv[1])
diff_json = sys.argv[2]

changelog_path = daemon_dir / "CHANGELOG.md"
if not changelog_path.exists():
    sys.exit(0)

diff_data = json.loads(diff_json)
removed_handlers = diff_data.get("removed", [])
renamed_handlers = diff_data.get("renamed", {})

if not removed_handlers and not renamed_handlers:
    sys.exit(0)

detector = BreakingChangesDetector(changelog_path)
warnings = detector.generate_warnings(
    removed_handlers=removed_handlers,
    renamed_handlers=renamed_handlers,
)

if warnings:
    print("", file=sys.stderr)
    print("⚠️  BREAKING CHANGES DETECTED IN CONFIG", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    for warning in warnings:
        print(warning, file=sys.stderr)
        print("", file=sys.stderr)
    print("Your config will be automatically updated during merge.", file=sys.stderr)
    print("Review the config after upgrade completes.", file=sys.stderr)
    print("", file=sys.stderr)
BREAKING_CHANGES_PY

        if [ "$BREAKING_CHANGES_EXIT" -ne 0 ]; then
            print_error "Breaking-changes detection crashed (exit $BREAKING_CHANGES_EXIT) - traceback above."
            print_warning "Continuing the upgrade; review $TARGET_CONFIG after it completes."
        fi
    fi
fi

# ============================================================
# Step 5a: Upgrade-guide reading list -- see run_pre_deploy_phase
# ============================================================

# The reading list and its proceed/abort gate run after Step 6, from
# run_pre_deploy_phase: only the target's tree holds the guide for the version
# being installed.

# ============================================================
# Step 6: Checkout target version
# ============================================================

log_step "6" "Checking out target version"

print_info "Fetching tags..."
git -C "$DAEMON_DIR" fetch --tags --quiet

# Verify target version exists
if ! git -C "$DAEMON_DIR" rev-parse --verify --quiet "${TARGET_VERSION}^{commit}" > /dev/null; then
    fail_fast "Version $TARGET_VERSION not found. Available versions:
$(git -C "$DAEMON_DIR" tag -l | sort -V | tail -10)"
fi

print_info "Checking out $TARGET_VERSION..."
git -C "$DAEMON_DIR" checkout "$TARGET_VERSION" --quiet
print_success "Checked out $TARGET_VERSION"

# Plan 00291: the daemon dir now sits on the target, so the stamp the venv
# will carry is known. A branch install announces itself here; a release
# install keeps the tag. An unguarded checkout of something no tag names is
# the one shape the gate exists to replace, so it is called out, not stamped.
_resolve_install_stamp
if [ "$BRANCH_INSTALL_STATE" != "armed" ]; then
    if ! EXACT_TAG_AT_HEAD="$(git -C "$DAEMON_DIR" describe --tags --exact-match HEAD 2>&1)"; then
        print_warning "$TARGET_VERSION is not a release tag ($EXACT_TAG_AT_HEAD). This install will not be recorded as a non-release; reinstall from a release tag."
    fi
fi

# Did that checkout replace THIS script? If so, the steps below are the ones
# the PREVIOUS release shipped, and anything the target added is missing from
# them. Recorded here and acted on at the very end of the run: re-exec'ing now
# would abandon Steps 7-17 half-done and force the child to rebuild the
# snapshot id, the config backup and the old-default baseline that Steps 3-5
# already produced. Completing this pass and then repeating it idempotently
# keeps the rollback contract intact and needs no state handover.
if [ -n "$LAYER2_SOURCE_FINGERPRINT_BEFORE" ] && [ -f "$LAYER2_TARGET_SCRIPT" ]; then
    if [ "$(cksum < "$LAYER2_TARGET_SCRIPT")" != "$LAYER2_SOURCE_FINGERPRINT_BEFORE" ]; then
        LAYER2_SOURCE_CHANGED=true
        print_warning "$TARGET_VERSION ships a different upgrade script than the one now running."
        print_info "The remaining steps come from the pre-upgrade script; a second pass will run from $TARGET_VERSION's own script at the end."
    fi
fi

# The target is checked out and nothing is deployed yet: the gate decides now,
# before Step 7 rebuilds the venv. A stop exits through the snapshot rollback.
run_pre_deploy_phase

# ============================================================
# Step 7: Recreate virtual environment (clean reinstall)
# ============================================================

log_step "7" "Recreating virtual environment"

# Plan 00099: use fingerprint-keyed venv so concurrent environments (container
# vs host, different Pythons) each keep their own healthy venv. ensure_venv
# rebuilds when the stamp is missing/stale and handles creation atomically.
VENV_PATH=$(ensure_venv "$DAEMON_DIR" "$INSTALL_STAMP" "${HOOKS_DAEMON_PYTHON:-python3}")
if [ -z "$VENV_PATH" ]; then
    fail_fast "ensure_venv returned empty path"
fi
VENV_PYTHON="$VENV_PATH/bin/python"

if ! verify_venv "$VENV_PYTHON" "$DAEMON_DIR"; then
    fail_fast "Virtual environment verification failed"
fi

# The target's venv is verified and nothing has been deployed into the project
# yet.
run_config_compatibility_check

# Plan 00099: clean up pre-v3.7.0 legacy venv to avoid confusion. Only remove
# the legacy path if we successfully provisioned a fingerprint-keyed venv at a
# distinct location.
LEGACY_VENV="$DAEMON_DIR/untracked/venv"
if [ -d "$LEGACY_VENV" ] && [ "$VENV_PATH" != "$LEGACY_VENV" ]; then
    print_info "Removing legacy pre-v3.7.0 venv at $LEGACY_VENV"
    rm -rf "$LEGACY_VENV"
fi

# ============================================================
# Step 8: Redeploy hook scripts
# ============================================================

log_step "8" "Redeploying hook scripts"
deploy_all_hooks "$PROJECT_ROOT" "$DAEMON_DIR" "normal" "$VENV_PYTHON"

# ============================================================
# Step 9: Redeploy settings.json
# ============================================================

log_step "9" "Redeploying settings.json"

TARGET_SETTINGS="$PROJECT_ROOT/.claude/settings.json"

# Step 3's snapshot already holds a pre-upgrade copy, so pass its path rather
# than making a second one. If Step 3 could not snapshot (it is best-effort and
# only warns), SNAPSHOT_ID is empty and the helper takes its own backup.
if [ -n "${SNAPSHOT_ID:-}" ]; then
    SETTINGS_SNAPSHOT_COPY="$(get_snapshot_dir "$DAEMON_DIR")/$SNAPSHOT_ID/files/config/settings.json"
else
    SETTINGS_SNAPSHOT_COPY=""
fi

deploy_settings_json_checked "$SETTINGS_JSON_SOURCE" "$TARGET_SETTINGS" "$SETTINGS_SNAPSHOT_COPY" \
    "$VENV_PYTHON" "${HOOKS_DAEMON_OLD_DEFAULT_SETTINGS:-}" \
    || fail_fast "Could not preserve the existing settings.json"

# ============================================================
# Step 10: Config preservation (merge customizations onto new default)
# ============================================================

log_step "10" "Merging config customizations"

NEW_DEFAULT_CONFIG="$EXAMPLE_CONFIG"

if [ -n "$OLD_DEFAULT_CONFIG" ] && [ -f "$OLD_DEFAULT_CONFIG" ] && [ -f "$NEW_DEFAULT_CONFIG" ] && [ -f "$TARGET_CONFIG" ]; then
    # Full config preservation: diff + merge + validate
    if preserve_config_for_upgrade "$VENV_PYTHON" "$PROJECT_ROOT" "$OLD_DEFAULT_CONFIG" "$NEW_DEFAULT_CONFIG"; then
        print_success "Config customizations preserved"
    else
        print_warning "Config preservation had issues - review config manually"
        print_info "Backup: $CONFIG_BACKUP"
    fi
elif [ ! -f "$TARGET_CONFIG" ] && [ -f "$NEW_DEFAULT_CONFIG" ]; then
    # No existing config - copy new default
    cp "$NEW_DEFAULT_CONFIG" "$TARGET_CONFIG"
    print_success "Installed new default config"
else
    print_info "Config preservation skipped (missing baseline or config)"
    if [ -n "$CONFIG_BACKUP" ]; then
        print_info "Your config backup: $CONFIG_BACKUP"
    fi
fi

# The baseline temp copy is cleaned up by the EXIT trap, not here — see
# cleanup_on_failure. Deleting it at this point covered only the happy path,
# and deleted Layer 1's handover along with it.

# ============================================================
# Step 11: Setup .gitignore
# ============================================================

log_step "11" "Verifying .gitignore"
setup_all_gitignores "$PROJECT_ROOT" "$DAEMON_DIR" "normal" || print_warning ".gitignore setup had warnings (non-fatal)"

# ============================================================
# Step 12: Redeploy slash commands
# ============================================================

log_step "12" "Redeploying slash commands"
deploy_slash_commands "$PROJECT_ROOT" "$DAEMON_DIR" "normal"

# ============================================================
# Step 13: Redeploy skills
# ============================================================

log_step "13" "Redeploying user-facing skills"

"$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" <<'SLOWPATH_SKILLS_PY'
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.skills import deploy_skills

daemon_source = Path(sys.argv[1])
project_root = Path(sys.argv[2])

try:
    deploy_skills(daemon_source, project_root)
    print("✓ Skills redeployed to .claude/skills/hooks-daemon/")
except Exception as e:
    print(f"✗ Skill redeployment failed: {e}")
    sys.exit(1)
SLOWPATH_SKILLS_PY

# ============================================================
# Step 13b: Redeploy the hooks-daemon bin wrapper (Plan 00192)
# ============================================================
#
# Daemon-owned tooling: overwritten on every upgrade so a stale wrapper can
# never outlive a fix. This step is what delivers the wrapper to installs that
# predate it — without it, existing projects would keep the broken
# "$PYTHON -m ..." guidance forever. DAEMON_DIR is the daemon root in both
# install modes.

log_step "13b" "Redeploying hooks-daemon CLI wrapper and echd-capture helper"

"$VENV_PYTHON" - "$DAEMON_DIR" <<'REDEPLOY_BIN_WRAPPER_PY'
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.bin_wrapper import deploy_bin_wrapper, deploy_echd_capture

try:
    target = deploy_bin_wrapper(Path(sys.argv[1]))
    print(f"✓ CLI wrapper redeployed to {target}")
    # Plan 00362 Task 1.3: this step is what delivers the helper to installs
    # that predate it, so pipe_blocker's guidance names a path that exists.
    helper = deploy_echd_capture(Path(sys.argv[1]))
    print(f"✓ echd-capture helper redeployed to {helper}")
except Exception as e:
    print(f"✗ CLI wrapper redeployment failed: {e}")
    sys.exit(1)
REDEPLOY_BIN_WRAPPER_PY

# ============================================================
# Step 14: Deploy plan workflow (config-driven SSoT — Plan 00136)
# ============================================================
#
# Runs AFTER config merge (Step 10) so config.plan_workflow.enabled reflects
# the upgraded config. Deployment is derived from that config (the SSoT the
# daemon reads), exactly as hooks/slash-commands/skills are redeployed every
# run. This closes the bug where mkplan.bash was never delivered on upgrade.

log_step "14" "Deploying plan workflow (if enabled in config)"

if "$VENV_PYTHON" - "$PROJECT_ROOT" "$TARGET_CONFIG" <<'SLOWPATH_PLAN_WORKFLOW_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.plan_workflow import deploy_plan_workflow_if_enabled

result = deploy_plan_workflow_if_enabled(Path(sys.argv[1]), Path(sys.argv[2]))
for msg in result.messages:
    print(f"  -> {msg}")
SLOWPATH_PLAN_WORKFLOW_PY
    print_success "Plan workflow deployment complete"
else
    print_warning "Plan workflow deployment had issues (non-fatal)"
fi

# ============================================================
# Step 14a: Core document deployment (config-driven SSoT — Plan 00334)
# ============================================================
#
# Daemon-owned core documents are refreshed on every upgrade, which is what
# lets an upstream correction reach an install set up long ago; the client's
# own override document beside each one is never touched. Gated per document
# on the subsystem whose guidance names it, NOT on the plan workflow above.

log_step "14a" "Deploying core documents (per-subsystem gates)"

if "$VENV_PYTHON" - "$PROJECT_ROOT" "$TARGET_CONFIG" <<'SLOWPATH_CORE_DOCS_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.core_docs import deploy_core_docs_if_enabled

result = deploy_core_docs_if_enabled(Path(sys.argv[1]), Path(sys.argv[2]))
for msg in result.messages:
    print(f"  -> {msg}")
SLOWPATH_CORE_DOCS_PY
    print_success "Core document deployment complete"
else
    print_warning "Core document deployment had issues (non-fatal)"
fi

# ============================================================
# Step 14b: Redeploy + arm ccy PTY supervisor (config-gated — Plan 00147/00148)
# ============================================================
#
# Refreshes .claude/ccy/claude-supervise.py from the upgraded daemon clone AND
# arms it (ensures ccy.env exports CCY_CLAUDE_WRAPPER) when a .claude/ccy/ dir is
# present and ccy.deploy_supervisor is not false, so ccy projects always run the
# current supervisor — and actually wrap claude with it — after an upgrade. An
# existing user-set CCY_CLAUDE_WRAPPER is left untouched.

log_step "14b" "Deploying + arming ccy supervisor (if a .claude/ccy/ project)"

if "$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" "$TARGET_CONFIG" <<'SLOWPATH_CCY_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.ccy_supervisor import deploy_ccy_supervisor_if_enabled

result = deploy_ccy_supervisor_if_enabled(
    Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
)
for msg in result.messages:
    print(f"  -> {msg}")
if result.recommend_enable:
    print("  -> TIP: set ccy.deploy_supervisor: true in .claude/hooks-daemon.yaml to keep this on")
SLOWPATH_CCY_PY
    print_success "ccy supervisor deployment complete"
else
    print_warning "ccy supervisor deployment had issues (non-fatal)"
fi

# ============================================================
# Step 14c: Deploy relay binary (Plan 00290 Phase 5 — explicit config choice only)
# ============================================================
#
# daemon.transport.relay_source is null by default and never runs implicitly
# (Phase 5 owner ruling): "build" compiles from source with plain rustc when a
# musl-capable toolchain is present, "download" fetches the digest-verified
# release asset matching TARGET_VERSION. Either way this is advisory-only —
# a failure never aborts the upgrade; the relay rung simply stays unprovisioned
# and every hook falls back to the permanent bash+python3 transport.

log_step "14c" "Deploying relay binary (if daemon.transport.relay_source is configured)"

if "$VENV_PYTHON" - "$DAEMON_DIR" "$PROJECT_ROOT" "$TARGET_VERSION" <<'SLOWPATH_RELAY_PY'; then
import sys
from pathlib import Path

from claude_code_hooks_daemon.install.forwarder_generator import load_transport_config
from claude_code_hooks_daemon.install.relay_deploy import deploy_relay_if_configured

daemon_dir = Path(sys.argv[1])
project_root = Path(sys.argv[2])
version_tag = sys.argv[3]

transport = load_transport_config(project_root)
result = deploy_relay_if_configured(daemon_dir, project_root, transport, version_tag=version_tag)
for msg in result.messages:
    print(f"  -> {msg}")
sys.exit(0 if (transport.relay_source is None or result.deployed) else 1)
SLOWPATH_RELAY_PY
    print_success "Relay binary provisioning complete"
else
    print_warning "Relay binary provisioning had issues (non-fatal; relay rung falls back to the legacy transport)"
fi

# ============================================================
# Step 15: Restart daemon and verify
# ============================================================

log_step "15" "Restarting daemon"

if ! restart_daemon_verified "$VENV_PYTHON"; then
    print_error "Daemon failed to start after upgrade"
    print_info "This may indicate config validation errors"
    print_info "Check: $DAEMON_DIR/bin/hooks-daemon status"

    if [ -n "$CONFIG_BACKUP" ]; then
        echo ""
        print_info "To restore previous config:"
        echo "  cp $CONFIG_BACKUP $TARGET_CONFIG"
        echo "  $DAEMON_DIR/bin/hooks-daemon restart"
    fi

    # Don't trigger rollback for daemon start failure - code is updated
    # User can fix config manually
    UPGRADE_STARTED=false
    exit 1
fi

# Clear version check cache to prevent stale upgrade indicators
rm -f "$DAEMON_DIR/untracked/version_check_cache.json"

# Plan 00100 Task 3.9: eager cleanup of stale venvs after the new daemon
# is verified RUNNING on $VENV_PATH. Order matters — cleanup runs AFTER
# restart_daemon_verified so a failed upgrade leaves prior state intact
# (rollback safety). Plain daemon start (non-upgrade) is unaffected; it
# still uses lazy-rebuild-via-stamp inside ensure_venv.
eager_cleanup_stale_venvs "$DAEMON_DIR" "$VENV_PATH"

# ============================================================
# Step 16: Post-upgrade validation
# ============================================================

log_step "16" "Running post-upgrade validation"
if ! run_post_install_checks "$PROJECT_ROOT" "$VENV_PYTHON" "$DAEMON_DIR" "false"; then
    print_error "Post-upgrade validation failed"
    print_info "The daemon may not be fully functional. Review the errors above."

    if [ -n "$CONFIG_BACKUP" ]; then
        echo ""
        print_info "To restore previous config:"
        echo "  cp $CONFIG_BACKUP $TARGET_CONFIG"
        echo "  $DAEMON_DIR/bin/hooks-daemon restart"
    fi

    # Don't trigger rollback - code is updated, but user needs to investigate
    UPGRADE_STARTED=false
    exit 1
fi

# ============================================================
# Step 16.5: Project-handler load validation (Plan 00143)
# ============================================================
#
# An upgrade can introduce a new REQUIRED handler method (e.g. get_claude_md,
# abstract since v2.30.0). Older project handlers that predate it then fail to
# load and are silently skipped — a protection regression. Surface it loudly at
# the moment it happens, but do NOT fail the upgrade: the daemon itself is
# healthy and skips the broken handlers safely; the user just needs to fix and
# restart. The session-start alert + `health` exit code (Plan 00143) keep
# nagging until they do.

log_step "16.5" "Validating project handlers"
if "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli validate-project-handlers; then
    print_success "All project handlers load correctly"
else
    echo ""
    print_warning "PROJECT PROTECTION DEGRADED: one or more project handlers failed to load"
    print_warning "after this upgrade and are NOT protecting your sessions."
    print_info "This usually means an upgrade added a required handler method an older"
    print_info "handler does not implement yet. The daemon started fine and skipped them."
    print_info "Fix the handler(s) above, then restart the daemon:"
    echo "  $DAEMON_DIR/bin/hooks-daemon restart"
    print_info "Until then, every new session will show a degraded-protection alert."
fi

# ============================================================
# Step 16.6: Regenerate handler documentation (Plan 00336 Phase 3)
# ============================================================
#
# A project carries two generated guidance artifacts, and only one of them was
# being refreshed here. The CLAUDE.md <hooksdaemon> block is rewritten by the
# Step 15 restart (DaemonController.initialise runs the ClaudeMdInjector);
# .claude/HOOKS-DAEMON.md was written by install_version.sh and then never
# again, so it described the INSTALLED version no matter how many upgrades
# later it was read. An upgrade that enables a new deny handler by default then
# denies an agent by a rule its own guidance does not document.
#
# Ordering: after the restart, so the document reflects the handler set that
# actually loaded rather than one the daemon might have failed to load.

log_step "16.6" "Regenerating handler documentation"
if "$VENV_PYTHON" -m claude_code_hooks_daemon.daemon.cli generate-docs --project-root "$PROJECT_ROOT"; then
    print_success "Regenerated .claude/HOOKS-DAEMON.md"
else
    print_warning "Failed to regenerate handler docs (non-fatal; run 'hooks-daemon regenerate-docs')"
fi

# ============================================================
# Step 17: Cleanup old snapshots
# ============================================================

log_step "17" "Cleanup"
cleanup_old_snapshots "$DAEMON_DIR" 3

# Get new version
NEW_VERSION="unknown"
if [ -f "$VERSION_FILE" ] && [ -f "$VENV_PYTHON" ]; then
    NEW_VERSION=$("$VENV_PYTHON" -c "
from claude_code_hooks_daemon.version import __version__
print(__version__)
" 2>/dev/null || echo "unknown")
fi

# ============================================================
# Complete
# ============================================================

# Disable rollback on success
UPGRADE_STARTED=false
consume_used_approval

print_header "Upgrade Complete"

print_success "Claude Code Hooks Daemon upgraded successfully!"
echo ""
echo "  Previous version: $CURRENT_VERSION"
if [ "$BRANCH_INSTALL_STATE" = "armed" ]; then
    echo "  Current version:  $NEW_VERSION (NON-RELEASE, stamped $INSTALL_STAMP)"
else
    echo "  Current version:  $NEW_VERSION"
fi
echo "  Config:           $TARGET_CONFIG"
echo "  Config backup:    ${CONFIG_BACKUP:-none}"
echo "  Rollback snapshot: ${SNAPSHOT_ID:-none}"
echo ""

# Check for upgrade guides
UPGRADE_DIR="$DAEMON_DIR/CLAUDE/UPGRADES"
if [ -d "$UPGRADE_DIR" ]; then
    echo "Version-specific upgrade notes:"
    echo "  ls $UPGRADE_DIR/"
    echo ""
fi

# Plan 00308: every upgrade ends with the config-optimisation review, unless
# explicitly opted out. Same --force-style detection as the compat check
# above -- this script has no proper flag parser, so match against $* and the
# UPGRADE_FLAGS passthrough.
#
# Plan 00322: the mandate claims THIS session and is printed BEFORE the
# restart instruction. Addressed to "your next Claude Code session", and
# printed after "exit your current session", it read as a hand-back note --
# a client upgrade duly filed it as an optional "run it at some point".
if [[ "$*" == *"--skip-config-optimisation"* ]] || [[ "${UPGRADE_FLAGS:-}" == *"--skip-config-optimisation"* ]]; then
    echo "Config-optimisation review skipped (--skip-config-optimisation)."
    echo "Run it yourself when ready: Skill tool, skill=hooks-daemon, args=optimise."
    echo ""
else
    echo "MANDATORY NEXT STEP -- do this NOW, in this session, before you"
    echo "report the upgrade as done and before the restart below: run the"
    echo "config-optimisation review (Skill tool: skill=hooks-daemon,"
    echo "args=optimise)."
    echo "It is not an optional follow-up and does not belong in a hand-back"
    echo "list: handlers new in $NEW_VERSION are registered and firing with"
    echo "their DEFAULT settings, and handlers this project has disabled or"
    echo "never configured stay that way until the review surfaces them."
    echo "It inventories disabled-but-relevant handlers, surfaces what is new,"
    echo "and produces a per-handler enable/skip recommendation list -- it"
    echo "never applies changes without your explicit confirmation."
    echo "Pass --skip-config-optimisation to this script to opt out."
    echo ""
fi

echo "IMPORTANT: after the review, restart Claude Code to activate upgraded hooks."
echo "  1. Exit your current Claude Code session"
echo "  2. Start a new Claude Code session"
echo ""

if [ "$BRANCH_INSTALL_STATE" = "armed" ]; then
    print_branch_install_banner "$TRACK_REF" "$TRACK_REASON" "$INSTALL_STAMP"
fi

# Second pass: everything above ran from the pre-upgrade script, because Step 6
# replaced this file after bash had already read it. Re-exec the target's OWN
# script so any step the new release added actually runs. Step 2 there sees the
# checkout already at the target and takes the idempotent deployment path,
# which is exactly the manual "run it again" that recovers this situation
# today -- performed automatically, so an install is never left short of what
# the release notes promised because nobody read the scrollback.
#
# The sentinel is exported so the child cannot repeat this; without it a script
# that legitimately differs on every run would re-exec forever. `exec` does not
# fire the EXIT trap, so no spurious rollback is triggered, and UPGRADE_STARTED
# is already false by this point.
if [ "$LAYER2_SOURCE_CHANGED" = true ] && [ -z "${HOOKS_DAEMON_UPGRADE_SECOND_PASS:-}" ]; then
    print_header "Second pass: running $TARGET_VERSION's own upgrade steps"
    print_info "The steps above came from the pre-upgrade script. Re-running from $LAYER2_TARGET_SCRIPT."
    export HOOKS_DAEMON_UPGRADE_SECOND_PASS=1
    export HOOKS_DAEMON_UPGRADE_PREVIOUS_VERSION="$CURRENT_VERSION"
    # "${@:4}" forwards only the trailing FLAGS. Plain "$@" would re-append the
    # three positionals that are already being passed explicitly, handing the
    # child each of them twice.
    exec bash "$LAYER2_TARGET_SCRIPT" "$PROJECT_ROOT" "$DAEMON_DIR" "$TARGET_VERSION" "${@:4}"
fi

exit 0
