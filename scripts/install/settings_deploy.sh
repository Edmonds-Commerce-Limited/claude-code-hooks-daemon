#!/bin/bash
#
# settings_deploy.sh - Deploy the daemon's settings.json without silent loss
#
# The daemon owns the wired-hook set in `.claude/settings.json`, so an upgrade
# has to redeploy it. But the same file is where a client keeps their own
# `statusLine`, their `permissions` block and their `plansDirectory` — and the
# deploy is a plain overwrite, so those go with it (Plan 00176).
#
# `upgrade_version.sh` did this from two places that behaved differently, and
# the one that runs MOST often was the less safe of the two:
#
#   - Step 9 copies after Step 3 has taken a full state snapshot containing
#     settings.json, and announces "Redeployed settings.json".
#   - The idempotent fast path copies and says NOTHING — and it exits before
#     Step 3, so no snapshot stands behind it. The script's own comment calls
#     that branch "the effective single deployment path for every client
#     upgrade".
#
# Two sites doing one job differently is what produced the gap, so this is one
# function both call. It takes a timestamped backup whenever nothing else is
# holding a copy, and says what it replaced either way.
#
# Usage:
#   source "$(dirname "$0")/install/settings_deploy.sh"
#   deploy_settings_json "$SOURCE" "$TARGET" "$SNAPSHOT_PATH_OR_EMPTY"
#

# Ensure output.sh is loaded
if [ -z "${OUTPUT_SH_LOADED+x}" ]; then
    INSTALL_LIB_DIR="$(dirname "${BASH_SOURCE[0]}")"
    source "$INSTALL_LIB_DIR/output.sh"
fi

#
# deploy_settings_json() - Copy settings.json, reporting anything it replaces
#
# Args:
#   $1 - source: the daemon's settings.json (absent = nothing to do)
#   $2 - target: the client's settings.json
#   $3 - snapshot_path: where a pre-upgrade copy already lives, or "" if none.
#        When empty this takes its own timestamped backup instead.
#
# Returns:
#   0 on success; 1 if a needed backup could not be written (the target is
#   left untouched — losing the file is the one outcome worth aborting for).
#
deploy_settings_json() {
    local source="$1"
    local target="$2"
    local snapshot_path="${3:-}"

    if [ ! -f "$source" ]; then
        print_verbose "No settings.json in daemon repo (using existing)"
        return 0
    fi

    # Only when the file actually DIFFERS. Warning on every upgrade would train
    # people to ignore it, and a `.bak-` per upgrade of an identical file is
    # just litter.
    if [ -f "$target" ] && ! cmp -s "$source" "$target"; then
        if [ -n "$snapshot_path" ]; then
            print_warning "Your settings.json differed from the daemon's and has been REPLACED."
            print_warning "  Pre-upgrade copy: $snapshot_path"
        else
            local backup
            backup="${target}.bak-$(date +%Y%m%d-%H%M%S)"
            if ! cp "$target" "$backup"; then
                print_error "Could not back up $target before replacing it - aborting"
                return 1
            fi
            print_warning "Your settings.json differed from the daemon's and has been REPLACED."
            print_warning "  Previous version saved as: $backup"
        fi
        print_warning "  Re-apply any customizations from it (Plan 00176 will merge them automatically)."
    fi

    # Checked, like the backup above. Reporting success without reading this
    # exit status made the caller's `|| fail_fast` unreachable: a failed copy
    # printed "Redeployed settings.json" and returned 0, so an upgrade carried
    # on over a settings.json that had never been written.
    if ! cp "$source" "$target"; then
        print_error "Could not deploy settings.json to $target - aborting"
        return 1
    fi
    print_success "Redeployed settings.json"
    return 0
}
