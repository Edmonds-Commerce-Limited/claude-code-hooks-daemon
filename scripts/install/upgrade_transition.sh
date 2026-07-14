#!/bin/bash
#
# upgrade_transition.sh - source-safe helpers describing the TRUE upgrade
# transition. Plan 00164 Phase 1.
#
# Root cause of the "already upgraded" confusion: Layer 1 (upgrade.sh) checks
# out the target tag BEFORE Layer 2 (upgrade_version.sh) evaluates idempotency,
# so Layer 2's `git describe --tags --exact-match` always equals the target and
# it printed the misleading `Already at version X` even when the actually-built
# venv (its `.daemon-version` stamp) was an OLDER version being refreshed.
#
# These helpers describe the transition between the INSTALLED version (the venv
# stamp — what was actually built/running) and the TARGET version, so the output
# is always truthful:
#
#   installed empty       -> "Installing <target>"           (fresh install)
#   installed == target   -> "Already at <target> ..."       (true no-op refresh)
#   installed != target   -> "Refreshing <installed> → <target> ..."  (real jump)
#
# Pure functions only — safe to `source` (no side effects at source time).

# _upgrade_transition_normalise <version>
# Print the version with exactly one leading 'v'. An empty input stays empty.
_upgrade_transition_normalise() {
    local version="${1:-}"
    if [ -z "$version" ]; then
        printf ''
        return 0
    fi
    case "$version" in
        v*) printf '%s' "$version" ;;
        *) printf 'v%s' "$version" ;;
    esac
}

# upgrade_transition_headline <installed_version> <target_version>
# The line printed at the START of the deployment block. Built into a single
# variable and emitted with ONE terminal printf so a $(...) capture is never
# corrupted (capture-corruption audit).
upgrade_transition_headline() {
    local installed target line
    installed="$(_upgrade_transition_normalise "${1:-}")"
    target="$(_upgrade_transition_normalise "${2:-}")"

    if [ -z "$installed" ]; then
        line="Installing $target"
    elif [ "$installed" = "$target" ]; then
        line="Already at $target — re-running deployment to refresh installed files"
    else
        line="Refreshing installed version: $installed → $target (rebuilding venv + redeploying)"
    fi
    printf '%s' "$line"
}

# upgrade_transition_summary <installed_version> <target_version>
# The line printed at the END on success. Single terminal printf (see above).
upgrade_transition_summary() {
    local installed target line
    installed="$(_upgrade_transition_normalise "${1:-}")"
    target="$(_upgrade_transition_normalise "${2:-}")"

    if [ -z "$installed" ]; then
        line="Installed $target"
    elif [ "$installed" = "$target" ]; then
        line="Re-verified $target (no version change)"
    else
        line="Upgraded $installed → $target"
    fi
    printf '%s' "$line"
}
