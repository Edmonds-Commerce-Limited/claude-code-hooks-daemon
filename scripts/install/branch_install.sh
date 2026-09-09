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
    echo ""
    echo "=========================================================================="
    echo "  WARNING: NON-RELEASE INSTALL (guarded branch install)"
    echo "  Tracking ref : $ref @ ${stamp##*.}"
    echo "  Install stamp: $stamp"
    echo "  Reason       : $reason"
    echo "  This is not a release. No rollback guarantee, no upgrade-guide coverage"
    echo "  until the release that contains it ships. status and every new session"
    echo "  will flag this install until it is reinstalled from a release tag."
    echo "=========================================================================="
    echo ""
}
