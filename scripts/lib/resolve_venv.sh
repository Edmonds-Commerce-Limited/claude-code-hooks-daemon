#!/usr/bin/env bash
#
# resolve_venv.sh — canonical bash library for venv resolution (Plan 00104).
#
# Public API (call after sourcing):
#
#   resolve_venv_python <daemon_dir> [--fallback-target]
#       Echoes the resolved venv's ``bin/python`` path on success.
#       With --fallback-target, on miss echoes the fingerprint-keyed
#       creation target instead of failing — used by ensure_venv flows
#       on a fresh clone where no venv exists yet.
#
#   resolve_venv_dir <daemon_dir> [--fallback-target]
#       Echoes the resolved venv directory (the parent of bin/python).
#
# Failure semantics (Plan 00104 Task 4.1):
#   - Sourced as a library (BASH_SOURCE[0] != $0): functions ``return``
#     non-zero on failure. The caller's shell options (set -e, pipefail)
#     are preserved — see "Subshell isolation" below.
#   - Invoked as a script (BASH_SOURCE[0] == $0): the dispatch tail at
#     the bottom of this file ``exit``s non-zero on failure.
#
# Subshell isolation (Plan 00104 Task 3.2 fix):
#   The internal resolution logic runs inside ``( set -euo pipefail; ... )``
#   so that none of -e / -u / -o pipefail leak into the caller. This is
#   the bug at venv-include.bash:8 where the unconditional ``set -euo
#   pipefail`` at file top kills callers that source venv-include for the
#   side-effect of the venv environment. The library MUST behave as a
#   pure function: caller's shell options survive sourcing.
#
# Interpreter precedence for invoking paths.py (the SSOT) (Plan 00103
# Decision 2/3 Rule A — venv-resident bin/python preferred so paths.py
# imports succeed even when host python3 is RHEL/CentOS 3.9):
#   1. $HOOKS_DAEMON_PYTHON (explicit override; validated by paths.py)
#   2. $HOOKS_DAEMON_VENV_PATH/bin/python (explicit override)
#   3. ${daemon_dir}/untracked/venv-*/bin/python (first executable hit)
#   4. python3 — ONLY when --fallback-target is passed (fresh-clone
#      bootstrap; paths.py module-load needs 3.11+ stdlib only).
#
# Plan 00104 ordering: this is Phase 4 Task 4.1 — the canonical library.
# Phase 5 collapses the 5 historical resolution sites into shims that
# source this file. Until Phase 5 lands, only the Phase 3 driver tests
# (test_venv_resolver_pipefail_cascade.py + test_venv_resolver_init_sh_*)
# exercise this library.

# ============================================================
# Source-path resolution (Plan 00104 Task 4.2)
# ============================================================
#
# This library lives at one of three locations:
#   1. self-install repo  : <repo>/scripts/lib/resolve_venv.sh
#   2. downstream clone   : <project>/.claude/hooks-daemon/scripts/lib/resolve_venv.sh
#   3. skill bundle       : <bundle>/scripts/lib/resolve_venv.sh
# In all three cases paths.py sits at:
#   <two-levels-up-from-lib>/src/claude_code_hooks_daemon/daemon/paths.py
#
# We resolve relative to ``BASH_SOURCE[0]`` (the file being sourced),
# not ``$0`` — sourcing a script does not change ``$0``, but
# ``BASH_SOURCE[0]`` always points at the sourced file even when the
# library is sourced from arbitrary cwd by an arbitrary caller.

# Use bash parameter expansion (not `dirname`) so resolution works even on a
# hostile PATH that omits coreutils — see field-regression test
# tests/acceptance/test_v391_field_regression.py which strips PATH down to a
# single fake directory. ${var%/*} drops the trailing /component.
_RV_LIB_DIR="${BASH_SOURCE[0]%/*}"
case "$_RV_LIB_DIR" in
    /*) ;;
    *) _RV_LIB_DIR="$PWD/$_RV_LIB_DIR" ;;
esac
# _RV_LIB_DIR is .../scripts/lib — strip the last two components to get
# the project root. ${var%/*/*} removes /scripts/lib in one expansion.
_RV_PROJECT_ROOT="${_RV_LIB_DIR%/*/*}"
_RV_PATHS_SCRIPT="${_RV_PROJECT_ROOT}/src/claude_code_hooks_daemon/daemon/paths.py"

# ============================================================
# Internal helpers
# ============================================================

# _rv_pick_python <daemon_dir> [--fallback-target]
#
# Echoes ONE usable interpreter to invoke paths.py with, following the
# precedence above. Returns 0 on success, 1 on miss (caller decides
# whether to error or use --fallback-target's bare-python3 path).
_rv_pick_python() {
    local daemon_dir="$1"
    local allow_python3="${2:-}"
    local candidate

    if [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
        echo "${HOOKS_DAEMON_PYTHON}"
        return 0
    fi
    if [ -n "${HOOKS_DAEMON_VENV_PATH:-}" ] && [ -x "${HOOKS_DAEMON_VENV_PATH}/bin/python" ]; then
        echo "${HOOKS_DAEMON_VENV_PATH}/bin/python"
        return 0
    fi
    for candidate in "${daemon_dir}"/untracked/venv-*/bin/python; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    # Fresh-clone bootstrap: no venv exists yet, but paths.py only needs
    # the stdlib (incl. tomllib for 3.11+) to compute the creation target.
    # Caller MUST be passing --fallback-target. ``command -v`` writes the
    # resolved path to stdout when found and exits non-zero when not — we
    # discard stdout and let stderr surface (mirrors the existing
    # error_hiding-clean pattern in scripts/install/venv_resolver.sh).
    if [ "$allow_python3" = "--fallback-target" ] && command -v python3 > /dev/null; then
        echo "python3"
        return 0
    fi
    return 1
}

# _rv_resolve_python_impl <daemon_dir> [--fallback-target]
#
# The actual resolution logic, wrapped in a subshell by callers so set
# -euo pipefail does not leak. Echoes the venv bin/python path (or the
# creation target when --fallback-target is set and no venv exists).
_rv_resolve_python_impl() {
    local daemon_dir="$1"
    local fallback_flag="${2:-}"

    if [ -z "$daemon_dir" ]; then
        echo "resolve_venv: daemon_dir required as first argument" >&2
        return 2
    fi
    if [ ! -d "$daemon_dir" ]; then
        echo "resolve_venv: daemon_dir does not exist: $daemon_dir" >&2
        return 2
    fi
    if [ ! -f "$_RV_PATHS_SCRIPT" ]; then
        echo "resolve_venv: paths.py SSOT missing at $_RV_PATHS_SCRIPT" >&2
        echo "  Reinstall the daemon so paths.py is present." >&2
        return 5
    fi

    local python_cmd
    if ! python_cmd="$(_rv_pick_python "$daemon_dir" "$fallback_flag")"; then
        echo "resolve_venv: no usable venv found under $daemon_dir/untracked/" >&2
        echo "  Searched: \$HOOKS_DAEMON_PYTHON, \$HOOKS_DAEMON_VENV_PATH/bin/python," >&2
        echo "    $daemon_dir/untracked/venv-*/bin/python" >&2
        if [ "$fallback_flag" != "--fallback-target" ]; then
            echo "  Invoke the hooks-daemon skill (install action) to create the venv, or pass" >&2
            echo "  --fallback-target if you intend to bootstrap from a fresh clone." >&2
        fi
        return 5
    fi

    local args=("$_RV_PATHS_SCRIPT" "resolve-venv" "--daemon-dir" "$daemon_dir")
    if [ "$fallback_flag" = "--fallback-target" ]; then
        args+=("--fallback-target")
    fi

    # Stderr is NOT silenced — surface real failures (ModuleNotFoundError,
    # broken venv) instead of hiding them behind a generic "venv not
    # found" message. See Plan 00103 Decision 2 + Plan 00104 critical
    # lesson "silent fallback hides regressions".
    local resolved
    if resolved="$("$python_cmd" "${args[@]}")"; then
        printf '%s\n' "$resolved"
        return 0
    fi
    local rv=$?
    echo "resolve_venv: paths.py resolve-venv failed (interpreter=$python_cmd, exit=$rv)" >&2
    return 5
}

# ============================================================
# Public API
# ============================================================

# resolve_venv_python <daemon_dir> [--fallback-target]
resolve_venv_python() {
    # Subshell isolation: ``set -euo pipefail`` and ``trap`` set inside
    # the subshell die with it. The caller's shell options are
    # preserved — fixes Plan 00104 Task 3.2 pipefail-cascade bug.
    (
        set -euo pipefail
        _rv_resolve_python_impl "$@"
    )
}

# resolve_venv_dir <daemon_dir> [--fallback-target]
resolve_venv_dir() {
    local python_path
    python_path="$(resolve_venv_python "$@")" || return $?
    # Strip the trailing /bin/python — works for venv layouts where
    # the python binary lives at <venv>/bin/python (POSIX). We don't
    # ship Windows support today, so /bin/ is sufficient.
    printf '%s\n' "${python_path%/bin/python}"
}

# ============================================================
# Script-mode dispatch
# ============================================================
#
# When invoked as ``bash scripts/lib/resolve_venv.sh python <daemon_dir>``
# (i.e. NOT sourced), dispatch to the public API and exit with its
# return code. Detection: BASH_SOURCE[0] equals $0 only when the file
# is being executed directly; sourced files have BASH_SOURCE[0] set
# to the file path while $0 is the parent process's name.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    case "${1:-}" in
        python)
            shift
            resolve_venv_python "$@"
            exit $?
            ;;
        dir)
            shift
            resolve_venv_dir "$@"
            exit $?
            ;;
        ""|-h|--help)
            cat >&2 <<'EOF'
Usage: resolve_venv.sh python <daemon_dir> [--fallback-target]
       resolve_venv.sh dir    <daemon_dir> [--fallback-target]

Or source this file and call:
       resolve_venv_python <daemon_dir> [--fallback-target]
       resolve_venv_dir    <daemon_dir> [--fallback-target]
EOF
            exit 2
            ;;
        *)
            echo "resolve_venv.sh: unknown subcommand '$1' (expected: python|dir)" >&2
            exit 2
            ;;
    esac
fi
