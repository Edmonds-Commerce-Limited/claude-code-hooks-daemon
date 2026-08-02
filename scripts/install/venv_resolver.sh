#!/bin/bash
#
# venv_resolver.sh — Plan 00104 Phase 5 Task 5.6 thin shim.
#
# Re-exports the canonical library's API under the historical install-time
# function names so the 9 callers (install.sh, upgrade_version.sh,
# debug_hooks.sh, validate_worktrees.sh, detect_location.sh,
# project_detection.sh, rollback.sh, run_strategy_pattern_check.sh,
# run_all.sh) keep working untouched.
#
# Public API:
#   resolve_existing_venv_python <daemon_dir>
#       Echoes the resolved venv's bin/python on success (exit 0). On
#       failure (no venv found, paths.py SSOT missing, paths.py crashed)
#       writes a stderr directive and returns 5.
#
#   resolve_existing_venv_dir <daemon_dir>
#       Echoes the venv directory.
#
# Both functions delegate to the canonical bash library at
# scripts/lib/resolve_venv.sh — there is NO --fallback-target here. The
# install-time API is "give me the venv that already exists, fail if none
# does"; the creation target is the bootstrapping caller's concern.
#
# Plan 00103 Decision 2/3 contracts (preserved by the canonical library):
#   - Stderr is NOT silenced — surface real failures (ModuleNotFoundError,
#     broken venv) instead of hiding them behind generic "venv not found".
#   - No silent fallback to ``untracked/venv/bin/python``  # python-var-guidance-exempt: names the retired path to document its rejection
#     — the unversioned legacy layout that v3.7.0 retired.
#   - Venv-resident interpreter is preferred over system ``python3`` for
#     invoking paths.py (RHEL/CentOS hosts have python3 → 3.9 which crashes
#     on tomllib import).

# Source-path resolution uses bash parameter expansion (no `dirname`/`cd`/`pwd`)
# so this file works on hostile PATHs that strip coreutils. Mirrors the
# canonical library's pattern — see scripts/lib/resolve_venv.sh and
# tests/acceptance/test_v391_field_regression.py.
_VR_DIR="${BASH_SOURCE[0]%/*}"
case "$_VR_DIR" in
    /*) ;;
    *) _VR_DIR="$PWD/$_VR_DIR" ;;
esac
# _VR_DIR is .../scripts/install — strip /install + /scripts to get
# project root. ${var%/*/*} removes the last two /-separated components.
_VR_PROJECT_ROOT="${_VR_DIR%/*/*}"
_VR_CANONICAL_LIB="${_VR_PROJECT_ROOT}/scripts/lib/resolve_venv.sh"

if [ ! -f "$_VR_CANONICAL_LIB" ]; then
    echo "❌ venv_resolver.sh: canonical library missing at $_VR_CANONICAL_LIB" >&2
    echo "   Reinstall the daemon so scripts/lib/resolve_venv.sh is present." >&2
    unset _VR_DIR _VR_PROJECT_ROOT _VR_CANONICAL_LIB
    # shellcheck disable=SC2317  # `return` is reachable when sourced
    return 5 2>/dev/null || exit 5
fi

# shellcheck disable=SC1090  # path is computed at runtime from BASH_SOURCE
source "$_VR_CANONICAL_LIB"
unset _VR_DIR _VR_PROJECT_ROOT _VR_CANONICAL_LIB

# resolve_existing_venv_python <daemon_dir>
#
# Install-time API: NO --fallback-target. If no venv exists, fail with rc 5
# and a stderr directive. Bootstrap callers that want the creation target
# call the canonical resolve_venv_python directly with --fallback-target.
resolve_existing_venv_python() {
    resolve_venv_python "$@"
}

# resolve_existing_venv_dir <daemon_dir>
#
# Same precedence as resolve_existing_venv_python, but returns the venv dir.
resolve_existing_venv_dir() {
    resolve_venv_dir "$@"
}
