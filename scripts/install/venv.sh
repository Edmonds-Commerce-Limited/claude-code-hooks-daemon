#!/bin/bash
#
# venv.sh - Unified virtual environment management using uv
#
# Provides functions to create and verify Python virtual environments at
# fingerprint-keyed paths using the uv package manager.
#
# Plan 00100 Task 1.2: `create_venv()` and `recreate_venv()` (legacy
# pre-v3.7.0 functions writing to `untracked/venv/`) were removed. The
# live entry point is `ensure_venv()`, which delegates to
# `create_venv_at_path()` for the fingerprint-keyed path.
#
# Usage:
#   source "$(dirname "$0")/venv.sh"
#   ensure_venv "$DAEMON_DIR"
#   verify_venv "$VENV_PYTHON"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

# Ensure uv is in PATH (installed in ~/.local/bin by default)
if [ -d "$HOME/.local/bin" ]; then
    export PATH="$HOME/.local/bin:$PATH"
fi

#
# verify_venv() - Verify venv exists and can import daemon package
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - daemon_dir: Path to daemon installation directory (for import test)
#
# Returns:
#   Exit code 0 if venv is valid, 1 if invalid
#
verify_venv() {
    local venv_python="$1"
    local daemon_dir="$2"

    if [ -z "$venv_python" ]; then
        print_error "verify_venv: venv_python parameter required"
        return 1
    fi

    # Check if venv Python exists
    if [ ! -f "$venv_python" ]; then
        print_error "Virtual environment Python not found: $venv_python"
        return 1
    fi

    # Check if Python is executable
    if [ ! -x "$venv_python" ]; then
        print_error "Virtual environment Python is not executable: $venv_python"
        return 1
    fi

    # Verify Python runs
    if ! "$venv_python" --version > /dev/null 2>&1; then
        print_error "Virtual environment Python failed to run: $venv_python"
        return 1
    fi

    print_verbose "Venv Python executable: $venv_python"

    # If daemon_dir provided, test import
    if [ -n "$daemon_dir" ] && [ -d "$daemon_dir" ]; then
        print_verbose "Testing daemon package import..."

        local import_test
        import_test=$("$venv_python" -c "
import sys
from pathlib import Path

# Add src to path
daemon_dir = Path('$daemon_dir')
sys.path.insert(0, str(daemon_dir / 'src'))

try:
    import claude_code_hooks_daemon
    print('OK')
except ImportError as e:
    print(f'IMPORT_ERROR: {e}')
" 2>&1)

        if [[ "$import_test" == "OK" ]]; then
            print_verbose "Daemon package imports successfully"
        else
            print_error "Daemon package import test failed: $import_test"
            print_error "Virtual environment may be missing dependencies"
            return 1
        fi
    fi

    print_success "Virtual environment verified"
    return 0
}

#
# get_venv_python_version() - Get Python version from venv
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#
# Returns:
#   Prints version string to stdout (e.g., "3.11.2")
#   Exit code 0 on success, 1 on failure
#
get_venv_python_version() {
    local venv_python="$1"

    if [ -z "$venv_python" ] || [ ! -x "$venv_python" ]; then
        return 1
    fi

    "$venv_python" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))' 2>/dev/null
}

# Version stamp file name — lives inside the venv directory
VENV_VERSION_STAMP=".daemon-version"

#
# stamp_venv_version() - Write daemon version into venv directory
#
# Called after successful venv creation to record which daemon version
# the venv was built for. Enables stale-venv detection on upgrade.
#
# Args:
#   $1 - venv_path: Path to venv directory (e.g., .../untracked/venv)
#   $2 - version: Version string to stamp (e.g., v3.1.0)
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
stamp_venv_version() {
    local venv_path="$1"
    local version="$2"

    if [ -z "$venv_path" ] || [ -z "$version" ]; then
        print_error "stamp_venv_version: venv_path and version required"
        return 1
    fi

    if [ ! -d "$venv_path" ]; then
        print_error "stamp_venv_version: venv directory does not exist: $venv_path"
        return 1
    fi

    echo "$version" > "$venv_path/$VENV_VERSION_STAMP"
    print_verbose "Stamped venv with version: $version"
    return 0
}

#
# get_venv_version() - Read daemon version from venv stamp
#
# Args:
#   $1 - venv_path: Path to venv directory
#
# Returns:
#   Prints version string to stdout (empty string if no stamp)
#   Exit code 0 always
#
get_venv_version() {
    local venv_path="$1"
    local stamp_file="$venv_path/$VENV_VERSION_STAMP"

    if [ -f "$stamp_file" ]; then
        cat "$stamp_file"
    else
        echo ""
    fi
}

#
# venv_version_matches() - Check if venv was built for the target version
#
# Args:
#   $1 - venv_path: Path to venv directory
#   $2 - target_version: Expected version string
#
# Returns:
#   Exit code 0 if versions match
#   Exit code 1 if mismatch or no stamp
#
venv_version_matches() {
    local venv_path="$1"
    local target_version="$2"

    if [ -z "$venv_path" ] || [ -z "$target_version" ]; then
        return 1
    fi

    local current_version
    current_version=$(get_venv_version "$venv_path")

    if [ -z "$current_version" ]; then
        print_verbose "No venv version stamp found (pre-stamp install)"
        return 1
    fi

    if [ "$current_version" = "$target_version" ]; then
        print_verbose "Venv version matches: $current_version"
        return 0
    else
        print_info "Venv version mismatch: have $current_version, need $target_version"
        return 1
    fi
}

#
# venv_lock_hash_matches() - Check if the venv's metadata lock_hash is current
#
# Plan 00100 Task 3.7: downgrade safety. The authoritative freshness signal
# is the `lock_hash` inside `.daemon-metadata.json`, not the legacy
# `.daemon-version` SemVer stamp. When dependencies are unchanged, a daemon
# upgrade or downgrade must reuse the existing venv.
#
# Shells out to the Python SSOT (paths.py check-venv-fresh) using the host
# python3 — stdlib-only, no venv required (by design, paths.py avoids Pydantic).
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#   $2 - venv_path: Path to venv directory to check
#
# Returns:
#   Exit code 0 if metadata lock_hash matches current project state
#   Exit code 1 otherwise (missing metadata, mismatched hash, no pyproject)
#
# Stderr from the Python SSOT is routed to print_verbose-level logging
# so diagnostic details remain visible when the daemon is started with
# HOOKS_DAEMON_VERBOSE_INSTALL=1. Stdout is discarded — the only interesting
# signal is the exit code.
#
venv_lock_hash_matches() {
    local daemon_dir="$1"
    local venv_path="$2"

    if [ -z "$daemon_dir" ] || [ -z "$venv_path" ]; then
        return 1
    fi

    # Plan 00104 Task 5.8: source the canonical library (scripts/lib/
    # resolve_venv.sh) so the "real venvs ship both bin/python and
    # bin/python3, fakes ship only one" rule lives in ONE place. Falls
    # back to in-place bin/python pick if the lib cannot be sourced —
    # venv.sh has historical callers (worktree setup, install_version)
    # that may run before the lib is on disk.
    #
    # Plan 00103 Decision 3 Rule A: do NOT probe the host for a generic
    # `python3` here. The caller has already guarded `[ -d "$venv_path" ]`
    # so the venv directory exists; use its own interpreter. If neither
    # bin/python nor bin/python3 is executable the venv is broken —
    # return 1 to force a rebuild rather than silently masquerading as fresh.
    #
    # BASH_SOURCE[0] inside a function points to the file the function
    # was defined in — venv.sh — regardless of whether INSTALL_LIB_DIR
    # is still set or has been clobbered by a sourcing caller.
    local _vlhm_install_dir
    _vlhm_install_dir="$(dirname "${BASH_SOURCE[0]}")"
    local venv_python=""
    local _vlhm_lib="${_vlhm_install_dir%/install}/lib/resolve_venv.sh"
    if [ -f "$_vlhm_lib" ]; then
        # shellcheck disable=SC1090
        source "$_vlhm_lib"
        venv_python="$(resolve_venv_python_in_venv "$venv_path")" || venv_python=""
    fi
    if [ -z "$venv_python" ]; then
        if [ -x "$venv_path/bin/python" ]; then
            venv_python="$venv_path/bin/python"
        elif [ -x "$venv_path/bin/python3" ]; then
            venv_python="$venv_path/bin/python3"
        else
            return 1
        fi
    fi

    # paths.py is invoked as a direct script (NOT `python -m ...`) so the
    # package __init__.py — which pulls Pydantic — is bypassed. Stays stdlib
    # only, so it loads even if the venv is mid-rebuild.
    local paths_script="$daemon_dir/src/claude_code_hooks_daemon/daemon/paths.py"
    if [ ! -f "$paths_script" ]; then
        return 1
    fi

    local stderr_capture
    stderr_capture="$(
        "$venv_python" "$paths_script" check-venv-fresh \
            --venv-path "$venv_path" \
            --daemon-dir "$daemon_dir" \
            2>&1 > /dev/null
    )"
    local rc=$?

    if [ -n "$stderr_capture" ]; then
        print_verbose "check-venv-fresh: $stderr_capture"
    fi
    return $rc
}

#
# ensure_venv() - Auto-bootstrap venv for current Python environment fingerprint
#
# Plan 00099: the entry point init.sh calls on every daemon start. Computes
# the fingerprint of the target Python, then:
#   - venv missing                  -> create + stamp
#   - venv present, stamp missing   -> recreate + stamp (lazy upgrade from pre-stamp builds)
#   - venv present, stamp mismatch  -> recreate + stamp
#   - venv present, stamp matches   -> no-op (fast path)
#
# Honors HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP=1 and CI=true to skip entirely
# (CI environments stub venvs out of band).
#
# Args:
#   $1 - daemon_dir: Path to daemon installation directory
#   $2 - target_version: Daemon version to stamp into the venv (e.g. v3.7.0)
#   $3 - python_bin (optional, default: python3): Target Python to fingerprint
#
# Side effect:
#   Prints the computed venv path to stdout on success so callers can
#   capture it (e.g. `VENV_PATH="$(ensure_venv ...)"`). Log messages go
#   to stderr via print_* helpers.
#
# Returns:
#   Exit code 0 on success (including skip), 1 on failure
#
ensure_venv() {
    local daemon_dir="$1"
    local target_version="$2"
    local python_bin="${3:-python3}"

    if [ -z "$daemon_dir" ] || [ -z "$target_version" ]; then
        print_error "ensure_venv: daemon_dir and target_version required"
        return 1
    fi

    # CI gate: allow opt-out for CI environments that stub venvs
    if [ "${HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP:-0}" = "1" ] || [ "${CI:-}" = "true" ]; then
        print_verbose "ensure_venv: skipped (HOOKS_DAEMON_SKIP_VENV_BOOTSTRAP or CI set)"
        return 0
    fi

    # Compute fingerprint via the SSOT helper. Must be sourced by the caller.
    if ! declare -F python_venv_fingerprint > /dev/null; then
        print_error "ensure_venv: python_venv_fingerprint not loaded — source scripts/install/python_fingerprint.sh first"
        return 1
    fi

    local fingerprint
    if ! fingerprint=$(python_venv_fingerprint "$python_bin"); then
        print_error "ensure_venv: failed to compute fingerprint for $python_bin"
        return 1
    fi

    local venv_path="$daemon_dir/untracked/venv-$fingerprint"

    # Plan 00100 Task 3.7: lock_hash is authoritative. A daemon upgrade or
    # downgrade with unchanged deps (pyproject.toml + uv.lock) must reuse the
    # existing venv — the legacy `.daemon-version` SemVer stamp is advisory.
    if [ -d "$venv_path" ] && venv_lock_hash_matches "$daemon_dir" "$venv_path"; then
        print_verbose "ensure_venv: lock_hash unchanged — reusing $venv_path"
        echo "$venv_path"
        return 0
    fi

    # Fallback fast path: no usable metadata but legacy stamp matches — no-op.
    # Kept for pre-Phase-3 venvs that predate `.daemon-metadata.json`.
    if [ -d "$venv_path" ] && venv_version_matches "$venv_path" "$target_version"; then
        print_verbose "ensure_venv: venv up-to-date at $venv_path (stamp match)"
        echo "$venv_path"
        return 0
    fi

    # Slow path: need to (re)create
    if [ -d "$venv_path" ]; then
        print_info "ensure_venv: stamp mismatch — rebuilding $venv_path"
        rm -rf "$venv_path"
    else
        print_info "ensure_venv: creating venv at $venv_path"
    fi

    HOOKS_DAEMON_PYTHON="$python_bin" \
        create_venv_at_path "$daemon_dir" "$venv_path" "true" || return 1

    stamp_venv_version "$venv_path" "$target_version" || return 1

    # Plan 00100 Task 3.3: persist atomic .daemon-metadata.json via the Python
    # SSOT so the daemon's startup resolver can treat the venv's python_path as
    # authoritative and compare the project lock_hash to decide stale/fresh.
    # Failure here is non-fatal — the venv still works, but startup will treat
    # the metadata as missing and fall back to fingerprint/scan precedence.
    if ! "$venv_path/bin/python" -m claude_code_hooks_daemon.daemon.cli \
        write-venv-metadata \
        --venv-path "$venv_path" \
        --fingerprint "$fingerprint" \
        --daemon-version "$target_version" \
        --project-root "$daemon_dir"; then
        print_verbose "ensure_venv: write-venv-metadata failed (non-fatal)"
    fi

    echo "$venv_path"
    return 0
}

#
# create_venv_at_path() - Create venv at an explicit path (fingerprint-keyed)
#
# Thin wrapper around `uv sync` that lets callers specify the venv location
# directly. Used by ensure_venv() — the public entry point — as part of the
# fingerprint-keyed venv scheme introduced in v3.7.0.
#
# Args:
#   $1 - daemon_dir: Path to daemon project (for `uv sync --project`)
#   $2 - venv_path: Absolute path where the venv should be created
#   $3 - quiet (optional, default: false)
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
create_venv_at_path() {
    local daemon_dir="$1"
    local venv_path="$2"
    local quiet="${3:-false}"

    if [ -z "$daemon_dir" ] || [ -z "$venv_path" ]; then
        print_error "create_venv_at_path: daemon_dir and venv_path required"
        return 1
    fi

    mkdir -p "$daemon_dir/untracked"
    if [ ! -f "$daemon_dir/untracked/.gitignore" ]; then
        echo "/untracked/" > "$daemon_dir/untracked/.gitignore"
    fi

    local python_args=()
    if [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
        python_args=(--python "$HOOKS_DAEMON_PYTHON")
    fi

    # Plan 00100 Task 0.1: hardlink-first with copy fallback.
    # - Plan 00047 set UV_LINK_MODE=copy as default to silence the "Failed to
    #   hardlink" warning on overlay-fs (container) installs.
    # - Plan 00100 v2 reverses the default: hardlink is faster and avoids the
    #   copy-then-rename file-visibility race (field bug 2026-04-23 on
    #   /srv/example-app/front). If uv emits the "Failed to hardlink"
    #   warning, retry once with UV_LINK_MODE=copy — preserving Plan 00047's
    #   container-safety behaviour as a fallback, not the default.
    unset UV_LINK_MODE  # start from default (hardlink)

    local uv_output="/tmp/uv_sync_output.$$.txt"
    local uv_rc=0

    # First attempt: default link mode (hardlink on most filesystems)
    if UV_PROJECT_ENVIRONMENT="$venv_path" uv sync --project "$daemon_dir" "${python_args[@]}" \
            > "$uv_output" 2>&1; then
        uv_rc=0
    else
        uv_rc=$?
    fi

    # Detect overlay-fs "Failed to hardlink files" warning and retry with copy.
    # Plan 00105 Phase 5 Task 5.2: announce loudly via print_warning rather
    # than print_verbose. The previous behaviour hid the fallback unless the
    # operator set HOOKS_DAEMON_VERBOSE_INSTALL=1, which is exactly the
    # silent-fallback antipattern flagged in project memory
    # `feedback_silent_fallback_antipattern.md`. The retry itself is preserved
    # (essential for overlay-fs container installs) — only the silence is gone.
    if [ -f "$uv_output" ] && grep -q "Failed to hardlink" "$uv_output"; then
        print_warning "uv hardlink failed (likely overlay-fs) — retrying with UV_LINK_MODE=copy. Set UV_LINK_MODE=copy in your environment to skip the hardlink attempt and silence this notice."
        rm -rf "$venv_path"  # clean slate for the retry
        if UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT="$venv_path" uv sync --project "$daemon_dir" "${python_args[@]}" \
                > "$uv_output" 2>&1; then
            uv_rc=0
        else
            uv_rc=$?
        fi
    fi

    if [ "$uv_rc" -ne 0 ]; then
        print_error "Failed to create virtual environment at $venv_path"
        if [ -f "$uv_output" ]; then
            cat "$uv_output" >&2
            rm -f "$uv_output"
        fi
        return 1
    fi

    # Plan 00100 Task 0.1: force metadata flush before verify_venv runs.
    # `uv sync` with copy mode does copy-then-rename; the rename may land in
    # the page cache without being visible to a subsequent `[ -f ]` check on
    # overlay-fs / NFS / slow disks. `sync -f <path>` is filesystem-scoped
    # (fast); plain `sync` is the macOS/fallback.
    #
    # Plan 00104 Task 5.3 / hostile review C-6: do NOT silence stderr.
    # The previous shape (sync -f, redirect-to-null, OR plain-sync) hid
    # every reason `sync -f` might fail behind a generic fallback —
    # exactly the antipattern documented in the project memory
    # `feedback_silent_fallback_antipattern.md` (the v3.9.0 field bug).
    # Capture stderr; treat known platform/fs limitations as silent
    # (macOS lacks `-f`, overlay-fs returns the "not supported" errno);
    # surface anything else through print_verbose so operators running with
    # HOOKS_DAEMON_VERBOSE_INSTALL=1 see real failures.
    local sync_stderr
    if sync_stderr="$(sync -f "$venv_path" 2>&1)"; then
        :
    else
        case "$sync_stderr" in
            *"Operation not supported"*|*"unrecognized option"*|*"-f: invalid option"*|*"illegal option"*|*"invalid option"*)
                : # documented platform/fs limitation — silent fallback OK
                ;;
            *)
                print_verbose "sync -f failed unexpectedly (falling back to plain sync): $sync_stderr"
                ;;
        esac
        sync
    fi

    if [ "$quiet" = "true" ]; then
        print_verbose "Virtual environment created at: $venv_path"
    else
        print_success "Virtual environment created at: $venv_path"
    fi

    rm -f "$uv_output"
    return 0
}

#
# install_package_editable() - Install package in editable mode
#
# Installs the daemon package in editable mode (-e) into the venv.
#
# Args:
#   $1 - venv_python: Path to venv Python binary
#   $2 - daemon_dir: Path to daemon installation directory
#   $3 - quiet (optional, default: false)
#
# Returns:
#   Exit code 0 on success, 1 on failure
#
install_package_editable() {
    local venv_python="$1"
    local daemon_dir="$2"
    local quiet="${3:-false}"

    if [ -z "$venv_python" ]; then
        fail_fast "install_package_editable: venv_python parameter required"
    fi

    if [ -z "$daemon_dir" ]; then
        fail_fast "install_package_editable: daemon_dir parameter required"
    fi

    if [ ! -f "$venv_python" ]; then
        fail_fast "install_package_editable: venv Python not found: $venv_python"
    fi

    print_info "Installing daemon package in editable mode..."

    # Use uv pip (which works with uv-created venvs)
    # uv pip install automatically uses the active venv or can be told which one to use
    local pip_cmd="uv pip install -e $daemon_dir --python $venv_python"

    if [ "$quiet" = "true" ]; then
        if $pip_cmd > /dev/null 2>&1; then
            print_success "Daemon package installed"
            return 0
        else
            print_error "Failed to install daemon package"
            return 1
        fi
    else
        if $pip_cmd; then
            print_success "Daemon package installed"
            return 0
        else
            print_error "Failed to install daemon package"
            return 1
        fi
    fi
}

#
# eager_cleanup_stale_venvs() - Plan 00100 Task 3.9
#
# Remove every `{daemon_dir}/untracked/venv*` entry whose absolute path
# differs from the current venv. Emits one log line per deletion:
#   "Removed stale venv: <path> (reason: <legacy-name|fingerprint-mismatch>)"
#
# Called by upgrade_version.sh AFTER restart_daemon_verified confirms the
# new daemon is RUNNING on the current venv — so a failed upgrade preserves
# prior state (rollback safety).
#
# Plain (non-upgrade) daemon start is UNCHANGED: lazy-rebuild-via-stamp in
# ensure_venv still governs, so a host venv is not evicted when a container
# starts up alongside it.
#
# Arguments:
#   $1 - daemon_dir      (absolute)
#   $2 - current_venv    (absolute, the venv the daemon was just verified on)
#
# Returns 0 always.
#
eager_cleanup_stale_venvs() {
    local daemon_dir="$1"
    local current_venv="$2"
    local untracked_dir="$daemon_dir/untracked"

    if [ -z "$daemon_dir" ] || [ -z "$current_venv" ]; then
        return 0
    fi
    if [ ! -d "$untracked_dir" ]; then
        return 0
    fi

    local current_abs
    if [ -d "$current_venv" ]; then
        current_abs="$(cd "$current_venv" && pwd)"
    else
        current_abs="$current_venv"
    fi

    local entry entry_abs reason
    for entry in "$untracked_dir"/venv "$untracked_dir"/venv-*; do
        [ -d "$entry" ] || continue
        entry_abs="$(cd "$entry" && pwd)"
        if [ "$entry_abs" = "$current_abs" ]; then
            continue
        fi

        case "$(basename "$entry_abs")" in
            venv) reason="legacy-name" ;;
            *) reason="fingerprint-mismatch" ;;
        esac

        echo "Removed stale venv: $entry_abs (reason: $reason)"
        rm -rf "$entry_abs"
    done

    return 0
}
