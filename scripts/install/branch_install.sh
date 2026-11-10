#!/bin/bash
#
# branch_install.sh - The guarded branch-install gate (Plan 00291)
#
# First-party only. A branch is installed by exporting BOTH of
#
#   HOOKS_DAEMON_UNSAFE_TRACK_REF          the ref to track (a branch name)
#   HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE  a non-empty reason
#
# and nothing else: there is no positional spelling and no flag. Exactly one
# of the two set is a mistake and is refused, never treated as "off".
#
# The resulting install is stamped vX.Y.Z+<ref>.<shortsha> (X.Y.Z from the
# installed commit's pyproject.toml), which status and every new session
# report as a non-release install. The full contract lives in the plan's
# design note; this file is the only implementation of it that Layer 2 and
# the venv stamping share. Layer 1 (scripts/upgrade.sh) cannot source this
# file because it may be running from a curl-fetched copy in /tmp, so it
# carries its own copy of the gate check -- keep the two in step.
#
# Source-safe: defines functions only. Depends on output.sh.
#

#
# branch_install_gate_state() - Evaluate the two-variable gate
#
# Prints "armed" when both variables are set and non-empty, "off" when
# neither is. Exactly one set (or set but empty) is a refusal: prints the
# name of the missing variable to stderr and returns 1.
#
branch_install_gate_state() {
    local ref="${HOOKS_DAEMON_UNSAFE_TRACK_REF:-}"
    local reason="${HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE:-}"

    if [ -z "$ref" ] && [ -z "$reason" ]; then
        echo "off"
        return 0
    fi
    if [ -n "$ref" ] && [ -n "$reason" ]; then
        echo "armed"
        return 0
    fi
    if [ -z "$ref" ]; then
        print_error "HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE is set but HOOKS_DAEMON_UNSAFE_TRACK_REF is not: a branch install needs both, refusing."
    else
        print_error "HOOKS_DAEMON_UNSAFE_TRACK_REF is set but HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE is empty: a branch install needs a reason, refusing."
    fi
    return 1
}

#
# branch_install_stamp() - The stamp for the commit a daemon dir is on
#
# Args:
#   $1 - daemon_dir: checkout whose HEAD is the installed commit
#   $2 - ref: the tracked ref (slashes become dashes in the stamp)
#
# Prints vX.Y.Z+<ref>.<shortsha>; returns 1 if the version cannot be read.
#
branch_install_stamp() {
    local daemon_dir="$1"
    local ref="$2"
    local pyproject="$daemon_dir/pyproject.toml"
    local version short_sha

    if [ ! -f "$pyproject" ]; then
        print_error "branch_install_stamp: no pyproject.toml at $daemon_dir"
        return 1
    fi
    version=$(awk -F'"' '/^version[[:space:]]*=/ { print $2; exit }' "$pyproject")
    if [ -z "$version" ]; then
        print_error "branch_install_stamp: pyproject.toml at $daemon_dir has no [project].version"
        return 1
    fi
    short_sha=$(git -C "$daemon_dir" rev-parse --short HEAD) || return 1
    echo "v${version}+${ref//\//-}.${short_sha}"
}

#
# print_branch_install_banner() - The loud warning every branch install prints
#
# Args:
#   $1 - ref, $2 - reason, $3 - stamp
#
print_branch_install_banner() {
    local ref="$1"
    local reason="$2"
    local stamp="$3"
    echo "" >&2
    echo "==========================================================================" >&2
    echo "  WARNING: NON-RELEASE INSTALL (guarded branch install)" >&2
    echo "  Tracking ref : $ref @ ${stamp##*.}" >&2
    echo "  Install stamp: $stamp" >&2
    echo "  Reason       : $reason" >&2
    echo "  This is not a release. No rollback guarantee, no upgrade-guide coverage" >&2
    echo "  until the release that contains it ships. status and every new session" >&2
    echo "  will flag this install until it is reinstalled from a release tag." >&2
    echo "==========================================================================" >&2
    echo "" >&2
}

#
# record_install_tracking() - Record what this install tracks (Plan 00594 Task 5.1)
#
# The stamp turns the ref's "/" into "-", so the exact ref, the full sha and the
# release installed before go into the venv's .daemon-metadata.json through the
# record-venv-tracking command. A release install (gate off) clears them.
# Non-fatal like write-venv-metadata: the venv works without the record, only
# the session-start check for a moved ref is lost, so it warns.
#
# Args:
#   $1 - venv_python, $2 - venv_path, $3 - daemon_dir (HEAD is the installed commit)
#   $4 - previous_release_tag (may be empty), read by read_previous_release_tag
#        BEFORE ensure_venv: the venv folder name does not change with the
#        version, so a rebuild wipes the record this would otherwise read.
#
record_install_tracking() {
    local venv_python="$1" venv_path="$2" daemon_dir="$3"
    local previous_release="${4:-}"
    local -a args=(--venv-path "$venv_path")

    if [ "$(branch_install_gate_state)" = "armed" ]; then
        local sha
        sha="$(git -C "$daemon_dir" rev-parse HEAD)" || return 0
        args+=(--tracked-ref "$HOOKS_DAEMON_UNSAFE_TRACK_REF" --tracked-sha "$sha")
        if [ -n "$previous_release" ]; then
            args+=(--last-release-tag "$previous_release")
        fi
    fi
    if ! "$venv_python" -m claude_code_hooks_daemon.daemon.cli record-venv-tracking "${args[@]}"; then
        print_warning "Could not record the tracking metadata in $venv_path; session start will not notice when the tracked ref moves"
    fi
    return 0
}

#
# read_previous_release_tag() - The release installed before the one being built
#
# Prints "vX.Y.Z" or nothing. A release stamp is its own answer; a branch stamp
# carries none, so the venv's own record supplies it. Call it before ensure_venv
# (see record_install_tracking).
#
# Args: $1 - venv_dir (may not exist), $2 - installed version stamp (may be empty)
#
read_previous_release_tag() {
    local venv_dir="$1" installed="${2:-}" recorded=""
    if [ -z "$installed" ]; then
        return 0
    fi
    if [[ "$installed" != *+* ]]; then
        echo "v${installed#v}"
        return 0
    fi
    if [ -f "$venv_dir/.daemon-metadata.json" ] \
        && recorded="$(grep -o '"last_release_tag": *"v[0-9.]*"' "$venv_dir/.daemon-metadata.json")"; then
        cut -d'"' -f4 <<<"$recorded"
    fi
    return 0
}
