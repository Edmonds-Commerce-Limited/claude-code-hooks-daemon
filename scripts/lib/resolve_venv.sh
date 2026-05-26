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
    # Real venvs ship both bin/python AND bin/python3, but bash test fakes
    # and some minimal layouts ship only one. Mirror paths.py's
    # _pick_interpreter (python preferred, python3 as fallback) so every
    # caller agrees on whether a venv is usable.
    if [ -n "${HOOKS_DAEMON_VENV_PATH:-}" ]; then
        if [ -x "${HOOKS_DAEMON_VENV_PATH}/bin/python" ]; then
            echo "${HOOKS_DAEMON_VENV_PATH}/bin/python"
            return 0
        fi
        if [ -x "${HOOKS_DAEMON_VENV_PATH}/bin/python3" ]; then
            echo "${HOOKS_DAEMON_VENV_PATH}/bin/python3"
            return 0
        fi
    fi
    for candidate in "${daemon_dir}"/untracked/venv-*/bin/python; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    for candidate in "${daemon_dir}"/untracked/venv-*/bin/python3; do
        if [ -x "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    # Fresh-clone bootstrap: no venv exists yet, but paths.py only needs
    # the stdlib (incl. tomllib for 3.11+) to compute the creation target.
    # Caller MUST be passing --fallback-target. Plan 00110 Task 4.5:
    # delegate to the canonical glob-and-sort helper so the host-a trap
    # (default ``python3`` is 3.9 even when 3.13/3.14 are installed under
    # versioned ``python3.13``/``python3.14`` names) is closed here too.
    # The helper is sibling to this file under scripts/lib/ in all three
    # layouts (self-install repo, downstream .claude/hooks-daemon/ clone,
    # skill bundle). Sourced lazily so a missing helper only impacts the
    # fallback path, not the steady-state cache-hit path.
    if [ "$allow_python3" = "--fallback-target" ]; then
        local discovery_lib="${_RV_LIB_DIR}/python_discovery.sh"
        if [ ! -f "$discovery_lib" ]; then
            echo "resolve_venv: python_discovery.sh missing at $discovery_lib" >&2
            echo "  Reinstall the daemon so the canonical discovery helper is present." >&2
            return 1
        fi
        # shellcheck source=/dev/null
        . "$discovery_lib"
        local pyproject="${_RV_PROJECT_ROOT}/pyproject.toml"
        local discovered
        if discovered="$(find_latest_python "3.11" "$pyproject")"; then
            echo "$discovered"
            return 0
        fi
        # find_latest_python already wrote an observed-interpreter
        # diagnostic to stderr — no second-guessing here.
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

    # Hot-path cache (Plan 00104 Phase 8 Task 8.1).
    # Steady-state hook fires resolve to the same venv every time, but
    # paths.py spawns python3 to compute the fingerprint MD5 — Python
    # startup alone is 50-100ms, blowing the <5ms budget defined in
    # PLAN.md Success Criteria #5. The cache stores
    # "<untracked_mtime> <python_path>" at
    # $daemon_dir/untracked/.python-cmd-cache and is invalidated by any
    # change to untracked/'s directory mtime (a venv added/removed bumps
    # it; modifications inside venv-*/ do not). Skipped for
    # --fallback-target since that's the bootstrap path, not steady-state.
    local untracked_dir="$daemon_dir/untracked"
    local cache_file="$untracked_dir/.python-cmd-cache"
    if [ "$fallback_flag" != "--fallback-target" ] \
        && [ -d "$untracked_dir" ] \
        && [ -f "$cache_file" ]; then
        local cached_mtime cached_path current_mtime
        if read -r cached_mtime cached_path < "$cache_file" \
            && current_mtime="$(stat -c %Y "$untracked_dir" 2>/dev/null)" \
            && [ -n "$cached_mtime" ] \
            && [ "$cached_mtime" = "$current_mtime" ] \
            && [ -n "$cached_path" ] \
            && [ -x "$cached_path" ]; then
            printf '%s\n' "$cached_path"
            return 0
        fi
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
        # Refresh hot-path cache (skip for --fallback-target). Two-step
        # write: truncate first to settle untracked/'s mtime (creating a
        # new file bumps it; truncating an existing file does not), then
        # stat the post-truncate mtime, then write the real content.
        # This ensures the recorded mtime equals what readers see on the
        # next call, so the cache hits.
        if [ "$fallback_flag" != "--fallback-target" ] && [ -d "$untracked_dir" ]; then
            local cache_mtime
            : > "$cache_file"
            cache_mtime="$(stat -c %Y "$untracked_dir" 2>/dev/null)"
            if [ -n "$cache_mtime" ]; then
                printf '%s %s\n' "$cache_mtime" "$resolved" > "$cache_file"
            fi
        fi
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
    # paths.py SSOT may return bin/python OR bin/python3 depending on
    # which interpreter the venv ships (real venvs have both, test fakes
    # often have only one). ${var%/bin/*} strips either suffix in one
    # parameter expansion. POSIX-only — no Windows support.
    printf '%s\n' "${python_path%/bin/*}"
}

# resolve_venv_python_in_venv <venv_path>
#
# Given an explicit venv directory (NOT a daemon_dir), echo its
# bin/python — falling back to bin/python3 — so callers that already
# know the venv path don't have to re-run the full precedence ladder.
# Used by venv.sh::venv_lock_hash_matches (Plan 00104 Task 5.8) which
# is given an explicit venv_path by ensure_venv after fingerprint
# computation. Centralising this pick here keeps the
# "real venvs ship both, test fakes often ship only one" rule in a
# single place — same DRY motivation that drove the canonical library.
#
# Returns 0 on success (interpreter on stdout), 1 if the venv does not
# exist or has no usable interpreter.
resolve_venv_python_in_venv() {
    local venv_path="$1"
    if [ -z "$venv_path" ] || [ ! -d "$venv_path" ]; then
        return 1
    fi
    if [ -x "$venv_path/bin/python" ]; then
        echo "$venv_path/bin/python"
        return 0
    fi
    if [ -x "$venv_path/bin/python3" ]; then
        echo "$venv_path/bin/python3"
        return 0
    fi
    return 1
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
