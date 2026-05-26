#!/bin/bash
# shellcheck shell=bash
#
# python_discovery.sh — canonical "find latest compatible Python on PATH" helper
#
# Plan 00110 Phase 2 Task 2.2 — single source of truth for Python interpreter
# discovery across every bash entry-point in the daemon (scripts/upgrade.sh,
# scripts/install/prerequisites.sh, the skill bootstrap install.sh, and
# scripts/lib/resolve_venv.sh). Replaces four WET implementations with one.
#
# Design constraints:
#
#   - Self-contained POSIX-ish bash (no python dependency). The skill bootstrap
#     install.sh runs BEFORE any python is guaranteed to be installed; the
#     helper must work in that environment.
#   - Glob-and-sort, not enumerate. Walk $PATH for python3.[1-9][0-9] and pick
#     the highest minor satisfying the floor. New CPython releases (3.14, 3.15,
#     ...) work the day they ship — no daemon release required to "support" them.
#   - Error messages MUST name interpreters observed during the glob, never a
#     hardcoded version that may not exist on the host (host-a trap).
#
# Usage:
#
#   . scripts/lib/python_discovery.sh
#   find_latest_python <min_major.min_minor> [pyproject_path]
#
# Arguments:
#
#   $1 — min_major.min_minor (e.g. "3.11"). Required. Floor below which no
#        interpreter will be accepted.
#   $2 — pyproject_path (optional). If provided AND the file contains a
#        parseable `requires-python = ">=X.Y"`, the floor is RAISED to that
#        value (never lowered).
#
# Output:
#
#   stdout — absolute path to the chosen interpreter on success.
#   stderr — diagnostic on failure (names every candidate observed during the
#            glob, never a hardcoded suggestion).
#
# Exit:
#
#   0 — compatible interpreter found
#   1 — none found (or env override invalid; or pyproject unreadable)
#
# Precedence ladder (first satisfied rung wins):
#
#   1. $HOOKS_DAEMON_PYTHON — explicit operator override. Validated against
#      the effective floor. On failure: fail fast — NEVER silently fall back to
#      PATH probing (that would mask the operator's broken configuration).
#   2. Glob $PATH for executables matching python3.[1-9][0-9], probe each
#      with `--version`, filter to those meeting the floor, sort by minor
#      number DESCENDING, pick the first.
#

# Re-source guard. The file MUST be sourced (not executed); a no-op return
# when already loaded is safe because `return` is valid inside a sourced file.
if [ -n "${_PYTHON_DISCOVERY_SH_LOADED:-}" ]; then
    return 0
fi
_PYTHON_DISCOVERY_SH_LOADED=1

# ----- internal helpers -----

# Print version "X.Y.Z" for a python interpreter, or fail.
# Parses the `Python X.Y.Z` format every CPython release emits to --version.
_pd_probe_version() {
    local cmd="$1"
    local output=""
    if [ -z "$cmd" ]; then
        return 1
    fi
    if [ ! -x "$cmd" ]; then
        if ! command -v "$cmd" > /dev/null; then
            return 1
        fi
    fi
    # `--version` of a real CPython writes to stdout in 3.4+; older interpreters
    # used stderr. Merge so we parse uniformly.
    if ! output="$("$cmd" --version 2>&1)"; then
        return 1
    fi
    case "$output" in
        "Python "*) printf '%s\n' "${output#Python }" ;;
        *) return 1 ;;
    esac
}

# Compare two versions "A.B" "C.D". Exit 0 if first >= second, else 1.
_pd_version_ge() {
    local a_maj a_min b_maj b_min
    a_maj="${1%%.*}"; a_min="${1#*.}"
    b_maj="${2%%.*}"; b_min="${2#*.}"
    case "$a_maj$a_min$b_maj$b_min" in *[!0-9]*) return 1 ;; esac
    if [ "$a_maj" -gt "$b_maj" ]; then return 0; fi
    if [ "$a_maj" -lt "$b_maj" ]; then return 1; fi
    [ "$a_min" -ge "$b_min" ]
}

# Parse `requires-python = ">=X.Y"` (or `~=X.Y`) from a pyproject.toml.
# Echo "X.Y" on stdout, or fail.
# Tolerates surrounding whitespace, single or double quotes, and trailing
# constraints like ">=3.13,<4".
_pd_parse_pyproject_floor() {
    local pyproject="$1"
    if [ ! -f "$pyproject" ]; then
        return 1
    fi
    local line value tail maj min
    while IFS= read -r line; do
        case "$line" in
            *requires-python*=*) : ;;
            *) continue ;;
        esac
        value="${line#*=}"
        value="${value# }"; value="${value# }"; value="${value# }"
        value="${value#\"}"; value="${value#\'}"
        value="${value%\"}"; value="${value%\'}"
        case "$value" in
            *">="*|*"~="*) tail="${value#*=}" ;;
            *) continue ;;
        esac
        # Skip leading non-digit chars (the operator and whitespace).
        while [ -n "$tail" ]; do
            case "$tail" in
                [0-9]*) break ;;
                *) tail="${tail#?}" ;;
            esac
        done
        # Capture leading X (major).
        maj=""
        while [ -n "$tail" ]; do
            case "$tail" in
                [0-9]*) maj="$maj${tail%"${tail#?}"}"; tail="${tail#?}" ;;
                *) break ;;
            esac
        done
        case "$tail" in
            .*) tail="${tail#.}" ;;
            *) continue ;;
        esac
        # Capture leading Y (minor).
        min=""
        while [ -n "$tail" ]; do
            case "$tail" in
                [0-9]*) min="$min${tail%"${tail#?}"}"; tail="${tail#?}" ;;
                *) break ;;
            esac
        done
        if [ -n "$maj" ] && [ -n "$min" ]; then
            printf '%s.%s\n' "$maj" "$min"
            return 0
        fi
    done < "$pyproject"
    return 1
}

# Walk $PATH, echo absolute paths to every executable matching the
# interpreter form `python3.<digits>` (single- or double-digit minor).
# Deduplicated by absolute path so a single binary present on multiple
# PATH entries appears once.
#
# Two globs are required to match BOTH `python3.9` (single-digit minor)
# AND `python3.13` (double-digit minor) WITHOUT also matching the
# `python3.13-config`, `python3.14-x86_64-config`, or `python3.13-gdb.py`
# adjuncts that share the prefix. A no-trailing-wildcard glob anchors
# the match to the digit(s) only — anything after them (a hyphen, a dot)
# is rejected by the glob itself.
_pd_glob_candidates() {
    local IFS=:
    local dir bin seen=" "
    for dir in $PATH; do
        if [ ! -d "$dir" ]; then
            continue
        fi
        for bin in "$dir"/python3.[0-9] "$dir"/python3.[1-9][0-9]; do
            if [ ! -e "$bin" ]; then
                continue
            fi
            if [ ! -x "$bin" ]; then
                continue
            fi
            case "$seen" in
                *" $bin "*) continue ;;
            esac
            seen="$seen$bin "
            printf '%s\n' "$bin"
        done
    done
}

# ----- public entry point -----

find_latest_python() {
    local floor="${1:-}"
    local pyproject="${2:-}"
    if [ -z "$floor" ]; then
        echo "find_latest_python: missing floor argument (expected MAJOR.MINOR)" >&2
        return 1
    fi

    # Raise floor from pyproject if provided and tighter than the arg.
    if [ -n "$pyproject" ]; then
        local pp_floor
        if pp_floor="$(_pd_parse_pyproject_floor "$pyproject")"; then
            if ! _pd_version_ge "$floor" "$pp_floor"; then
                floor="$pp_floor"
            fi
        fi
    fi

    # Rung 1: $HOOKS_DAEMON_PYTHON explicit override.
    if [ -n "${HOOKS_DAEMON_PYTHON:-}" ]; then
        local ov_ver ov_path ov_short
        if ! ov_ver="$(_pd_probe_version "$HOOKS_DAEMON_PYTHON")"; then
            echo "HOOKS_DAEMON_PYTHON=$HOOKS_DAEMON_PYTHON is not a usable Python interpreter." >&2
            echo "Refusing to fall back to PATH discovery — that would mask the broken override." >&2
            echo "Unset HOOKS_DAEMON_PYTHON to let discovery probe \$PATH." >&2
            return 1
        fi
        ov_short="${ov_ver%.*}"
        if ! _pd_version_ge "$ov_short" "$floor"; then
            echo "HOOKS_DAEMON_PYTHON=$HOOKS_DAEMON_PYTHON reports Python $ov_ver, below required floor $floor." >&2
            echo "Point HOOKS_DAEMON_PYTHON at a Python $floor+ interpreter, or unset it to let discovery probe \$PATH." >&2
            return 1
        fi
        # Resolve to absolute path. If `command -v` cannot resolve (because the
        # override is already absolute), use the override as-is.
        if ! ov_path="$(command -v "$HOOKS_DAEMON_PYTHON")"; then
            ov_path="$HOOKS_DAEMON_PYTHON"
        fi
        printf '%s\n' "$ov_path"
        return 0
    fi

    # Rung 2: glob-and-sort PATH discovery.
    local candidate ver short minor
    local observed=""
    local best_path="" best_minor=-1
    while IFS= read -r candidate; do
        if [ -z "$candidate" ]; then
            continue
        fi
        if ! ver="$(_pd_probe_version "$candidate")"; then
            continue
        fi
        observed="$observed  ${candidate##*/} ($ver)\n"
        short="${ver%.*}"
        if ! _pd_version_ge "$short" "$floor"; then
            continue
        fi
        minor="${short#*.}"
        case "$minor" in *[!0-9]*|"") continue ;; esac
        if [ "$minor" -gt "$best_minor" ]; then
            best_minor="$minor"
            best_path="$candidate"
        fi
    done <<EOF
$(_pd_glob_candidates)
EOF

    if [ -n "$best_path" ]; then
        printf '%s\n' "$best_path"
        return 0
    fi

    # Failure: name every interpreter we OBSERVED during the glob, never a
    # hardcoded suggestion (the host-a trap).
    if [ -z "$observed" ]; then
        echo "No python3.NN interpreter found on \$PATH." >&2
        echo "Install Python $floor or newer (e.g. python$floor) and ensure it is on \$PATH," >&2
        echo "or set HOOKS_DAEMON_PYTHON to the absolute path of a Python $floor+ interpreter." >&2
    else
        echo "No interpreter on \$PATH meets the required floor $floor." >&2
        echo "Observed candidates (all below floor):" >&2
        printf "%b" "$observed" >&2
        echo "Install a Python $floor+ interpreter (e.g. python$floor) and ensure it is on \$PATH," >&2
        echo "or set HOOKS_DAEMON_PYTHON to the absolute path of a Python $floor+ interpreter." >&2
    fi
    return 1
}
