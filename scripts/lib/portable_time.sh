#!/usr/bin/env bash
#
# portable_time.sh — epoch seconds without a mandatory PATH lookup.
#
# Plan 00466 N30: `date +%s` is looked up on PATH, and the scripts that
# build/repair a project's venv exist to survive a hostile or stripped
# PATH -- the same hazard Plan 00466 N1 fixed for `sleep` in
# resolve_venv.sh (commit 766677c1). Several call sites fed `$(date +%s)`
# straight into an arithmetic expression or a numeric `[ ]` test; with
# `date` unreachable that embeds an EMPTY string, which is not a loud
# failure but a silently-wrong number that changes which branch runs.
#
# Bash 4.2+ ships a builtin substitute (`printf '%(...)T'`) that needs no
# PATH lookup at all. Bash 3.2 -- macOS's system /bin/bash, still the
# default there -- has no such builtin, so a script that must also run on
# macOS falls back to `date` when PATH has one (the ordinary case there:
# a hostile/stripped PATH is a bootstrap scenario, not "date does not
# exist on this host"). Only when NEITHER is available does this fail --
# and it fails LOUDLY (a clear stderr message and a non-zero return),
# never with a silently-wrong number.
#
# Public API:
#   _hp_epoch_seconds
#       Echoes the current epoch second count on stdout. Returns 1 (with
#       a diagnostic on stderr) when no source is available.
#   _hp_timestamp <strftime-format> [--utc]
#       Echoes the current time formatted per <strftime-format> (the same
#       syntax `date`/bash's `printf '%()T'` both accept, e.g.
#       "%Y%m%d-%H%M%S"). Same fallback and failure semantics as
#       _hp_epoch_seconds. For backup-filename/snapshot-ID/log-entry
#       timestamps across the hostile-PATH-survival file set.

# _hp_bash_supports_printf_time() - Does this bash have `printf '%()T'`?
#
# A separate, overridable function (rather than inlining the version test
# in `_hp_epoch_seconds`) so tests can force the bash-3.2 fallback path by
# redefining this after sourcing, regardless of the bash version actually
# running the test -- the alternative would need a real bash 3.2 binary in
# CI to exercise that branch at all.
_hp_bash_supports_printf_time() {
    ((BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 2)))
}

_hp_epoch_seconds() {
    if _hp_bash_supports_printf_time; then
        printf '%(%s)T' -1
        return 0
    fi
    if command -v date > /dev/null; then
        date +%s
        return 0
    fi
    echo "_hp_epoch_seconds: no epoch-second source available (bash < 4.2 and no 'date' on PATH)" >&2
    return 1
}

# _hp_timestamp <strftime-format> [--utc] - see Public API above.
#
# `TZ=UTC0` prefixing a REGULAR builtin (`printf`, unlike a SPECIAL builtin
# such as `.`/`eval`/`export`) scopes the assignment to that one command --
# it does not leak into the rest of the script, exactly like prefixing an
# external command. Verified: `TZ=UTC0 printf '%(%Y)T' -1` prints in UTC and
# `$TZ` is unset again immediately after.
_hp_timestamp() {
    local fmt="$1" utc="${2:-}"
    if _hp_bash_supports_printf_time; then
        if [ "$utc" = "--utc" ]; then
            TZ=UTC0 printf "%($fmt)T" -1
        else
            printf "%($fmt)T" -1
        fi
        return 0
    fi
    if command -v date > /dev/null; then
        if [ "$utc" = "--utc" ]; then
            date -u "+$fmt"
        else
            date "+$fmt"
        fi
        return 0
    fi
    echo "_hp_timestamp: no timestamp source available (bash < 4.2 and no 'date' on PATH)" >&2
    return 1
}
