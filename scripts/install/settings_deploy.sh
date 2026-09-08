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

# Exit status the settings-merge CLI uses for "I refused, nothing was written".
# Deliberately not 1: a 1 from this step means ABORT to the calling scripts, and
# aborting the idempotent fast path leaves new forwarders over old settings with
# no snapshot to roll back to. Kept in step with ESCALATION_EXIT_CODE in
# src/claude_code_hooks_daemon/install/settings_merge.py by a test.
SETTINGS_MERGE_ESCALATED=3

# Raised to 1 by deploy_settings_json_checked when a merge escalated, so the end
# of a run can say so once more. Exported because the scripts that SOURCE this
# library are the ones that read it, which shellcheck cannot see from here.
SETTINGS_NEEDS_ATTENTION=0
export SETTINGS_NEEDS_ATTENTION

#
# deploy_settings_json() - Merge settings.json, reporting anything it changes
#
# The daemon owns the wired-hook block; the client owns everything else in the
# same file. A plain `cp` refreshes the first by destroying the second, so this
# MERGES (Plan 00176) — and the CLIENT's document is the one being edited,
# because a merge cannot lose what it does not look at.
#
# Args:
#   $1 - source: the daemon's settings.json (absent = nothing to do)
#   $2 - target: the client's settings.json
#   $3 - snapshot_path: where a pre-upgrade copy already lives, or "" if none.
#        When empty this takes its own timestamped backup instead.
#   $4 - venv_python: interpreter that can import the daemon, or "" if none.
#   $5 - old_default: the PREVIOUS version's settings.json, or "" if no
#        handover captured one. Without it no baseline is guessed.
#
# Returns:
#   0 on success; $SETTINGS_MERGE_ESCALATED when nothing was written and a human
#   needs to look (the caller should WARN and carry on, not abort); 1 if a
#   needed backup could not be written, which is the one outcome worth aborting
#   a deploy for.
#
deploy_settings_json() {
    local source="$1"
    local target="$2"
    local snapshot_path="${3:-}"
    local venv_python="${4:-}"
    local old_default="${5:-}"

    if [ ! -f "$source" ]; then
        print_verbose "No settings.json in daemon repo (using existing)"
        return 0
    fi

    # Nothing on disk to lose, so there is nothing to protect and nothing to
    # merge: the shipped file IS the answer.
    if [ ! -f "$target" ]; then
        if ! cp "$source" "$target"; then
            print_error "Could not deploy settings.json to $target - aborting"
            return 1
        fi
        print_success "Installed settings.json"
        return 0
    fi

    # An identical file has nothing to merge INTO and nothing to lose, so this
    # returns before the interpreter check below — otherwise the commonest case
    # of all, a project already current, would escalate for want of a tool it
    # never needed.
    if cmp -s "$source" "$target"; then
        print_verbose "settings.json already matches the daemon's"
        return 0
    fi

    # Past here the file DIFFERS, which is exactly the case the merge may
    # rewrite — so it is also the right trigger for taking the copy. Backing up
    # an identical file would just be litter, and warning on every upgrade would
    # train people to ignore the warning.
    if [ -n "$snapshot_path" ]; then
        print_warning "Your settings.json differs from the daemon's; merging."
        print_warning "  Pre-upgrade copy: $snapshot_path"
    else
        local backup
        backup="${target}.bak-$(date +%Y%m%d-%H%M%S)"
        if ! cp "$target" "$backup"; then
            print_error "Could not back up $target before merging it - aborting"
            return 1
        fi
        print_warning "Your settings.json differs from the daemon's; merging."
        print_warning "  Previous version saved as: $backup"
    fi

    # Without an interpreter that can import the daemon there is no merge, and
    # the old behaviour — overwrite anyway — is precisely the data loss this
    # function exists to stop. Refuse instead, and say so.
    if [ -z "$venv_python" ] || [ ! -x "$venv_python" ]; then
        print_warning "No daemon interpreter available to merge settings.json."
        print_warning "  Left unchanged at $target; its hook registrations may be stale."
        return "$SETTINGS_MERGE_ESCALATED"
    fi

    local merge_status=0
    if [ -n "$old_default" ]; then
        "$venv_python" -m claude_code_hooks_daemon.daemon.cli settings-merge \
            --client "$target" --new-default "$source" --old-default "$old_default" ||
            merge_status=$?
    else
        "$venv_python" -m claude_code_hooks_daemon.daemon.cli settings-merge \
            --client "$target" --new-default "$source" || merge_status=$?
    fi

    case "$merge_status" in
        0)
            print_success "Merged settings.json"
            return 0
            ;;
        "$SETTINGS_MERGE_ESCALATED")
            print_warning "settings.json needs a human; see the message above."
            return "$SETTINGS_MERGE_ESCALATED"
            ;;
        *)
            print_error "Could not merge settings.json into $target - aborting"
            return 1
            ;;
    esac
}

#
# deploy_settings_json_checked() - deploy_settings_json with the caller contract
#
# Every call site wants the same three-way answer, and writing it out three
# times is how the two upgrade sites drifted apart in the first place. An
# escalation must NOT reach the caller's `|| fail_fast`: on the idempotent fast
# path the forwarders are already redeployed and the rollback snapshot does not
# exist yet, so aborting leaves a half-state with nothing to undo it — worse
# than finishing with the client's file intact and a warning on screen.
#
# Sets SETTINGS_NEEDS_ATTENTION=1 when a human has to look, so the end of the
# run can say so once more.
#
# Args: the same five deploy_settings_json takes.
# Returns: 0 when the upgrade should continue, 1 when it should abort.
#
deploy_settings_json_checked() {
    local status=0
    deploy_settings_json "$@" || status=$?

    if [ "$status" -eq 0 ]; then
        return 0
    fi
    if [ "$status" -eq "$SETTINGS_MERGE_ESCALATED" ]; then
        SETTINGS_NEEDS_ATTENTION=1
        return 0
    fi
    return 1
}
