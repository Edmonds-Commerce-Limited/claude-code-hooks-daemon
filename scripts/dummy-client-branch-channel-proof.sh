#!/bin/bash
#
# dummy-client-branch-channel-proof.sh — Plan 00594 Task 5.1 end-to-end proof.
#
# Drives the REAL upgrade.sh in the client fixture built by
#   scripts/dummy-client-repo.sh create --bare-remote
# through the branch channel: track a branch, see it reported as not moved,
# move it, see the move reported, re-track, see a failed listing reported as
# "not checked", return to the last release in one step, then pin a full sha
# and return again. Every step is asserted; the first failed assertion stops
# the run with a non-zero exit.
#
# OFFLINE BY CONSTRUCTION. The daemon dir is a clone of the fixture's local
# bare remote, so upgrade.sh fetches only from that path. Every git command
# here and below runs with GIT_ALLOW_PROTOCOL=file, so any attempt to reach an
# https/ssh/git URL fails loudly instead of silently using the network. uv runs
# with UV_OFFLINE=1. upgrade.sh's last-resort helper download is pointed at an
# unusable file:// base URL. The tracked branch and its moves are made in a
# scratch clone of the bare and pushed to the bare, never in this repository.
#
# THE MOVE CHECK LISTS A FIXED URL. version_check reads the tracked branch from
# this project's GitHub URL, not from the clone's origin. For the report steps
# only, a private global git config rewrites that URL to the bare remote (or,
# for the failed-listing step, to a path that does not exist). That rewrite is
# never in upgrade.sh's environment. So this proves the report LOGIC against a
# real listing; it does not prove the client's origin is the one listed.
#
# The tip cache is keyed by ref and installed sha with a TTL, so a cached "has
# not moved" would mask a move inside the TTL. Each report step runs the
# handler with a zero TTL and an emptied tip cache; that is recorded in the
# evidence, not hidden.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
FIXTURE="$REPO_ROOT/scripts/dummy-client-repo.sh"
DUMMY_ROOT="$REPO_ROOT/untracked/dummy-client-repo"
DAEMON_DIR="$DUMMY_ROOT/.claude/hooks-daemon"
BARE="$REPO_ROOT/untracked/dummy-client-repo-remote.git"
WORK="$REPO_ROOT/untracked/scratch/branch-channel-proof"
BRANCH="proof/branch-channel"
GITHUB_URL="https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git"

export GIT_ALLOW_PROTOCOL=file
export GIT_TERMINAL_PROMPT=0
export UV_OFFLINE=1
export HOSTNAME="dummy-client-repo"

step() { printf '\n=== %s\n' "$1"; }
ok() { printf 'PASS %s\n' "$1"; }
fail() {
    printf 'FAIL %s\n' "$1" >&2
    exit 1
}

# --- preconditions ----------------------------------------------------------

[ -d "$BARE" ] || fail "no bare remote at $BARE: run $FIXTURE create --bare-remote"
[ "$(git -C "$DAEMON_DIR" config --get-all remote.origin.url)" = "$BARE" ] \
    || fail "the daemon dir's origin is not the bare remote; refusing to run upgrade.sh"
# shellcheck source=lib/resolve_venv.sh
source "$REPO_ROOT/scripts/lib/resolve_venv.sh"
PY="$(resolve_venv_python "$DAEMON_DIR")"
TAG="$(git -C "$BARE" tag --list)"
[ -n "$TAG" ] || fail "the bare remote has no release tag"
UPGRADE_SH="$DAEMON_DIR/scripts/upgrade.sh"

# --- helpers ----------------------------------------------------------------

# state FIELD — one field of the running venv's stamp and tracking record.
state() {
    (cd "$DUMMY_ROOT" && "$PY" -c '
import sys
from pathlib import Path
from claude_code_hooks_daemon.daemon.metadata import read_daemon_metadata
from claude_code_hooks_daemon.install.install_stamp import read_install_stamp
field = sys.argv[1]
if field == "stamp":
    stamp = read_install_stamp()
    print(stamp.raw if stamp else "")
else:
    meta = read_daemon_metadata(Path(sys.prefix))
    value = getattr(meta, field) if meta else None
    print(value or "")
' "$1")
}

# report REWRITE_TARGET — the version_check advisory, with the fixed GitHub URL
# rewritten (global scope, this subprocess only) to REWRITE_TARGET.
report() {
    local gitconfig="$WORK/gitconfig-report"
    printf '[url "%s"]\n\tinsteadOf = %s\n' "$1" "$GITHUB_URL" > "$gitconfig"
    rm -f "$DUMMY_ROOT/untracked/version_check_tip_cache.json" \
        "$DAEMON_DIR/untracked/version_check_tip_cache.json"
    (cd "$DUMMY_ROOT" && GIT_CONFIG_GLOBAL="$gitconfig" GIT_CONFIG_NOSYSTEM=1 "$PY" -c '
from claude_code_hooks_daemon.handlers.session_start.version_check import VersionCheckHandler
handler = VersionCheckHandler()
handler._cache_ttl_hours = 0
result = handler.handle({"hook_event_name": "SessionStart"})
print("\n".join(result.context or []))
')
}

# upgrade [ARGS...] — the real Layer 1, as a client runs it. Tracking
# variables, when wanted, are given by the caller through the environment.
# The pre-deploy gate stops (exit 3) until the listed upgrade guides are
# confirmed read; the proof then does what the client is told to: re-run the
# same command with the digest the gate printed. Any other failure stops it.
upgrade() {
    local log="$WORK/upgrade-$RANDOM.log" rc=0 digest
    HOOKS_DAEMON_UPGRADE_BASE_URL="file:///nonexistent-upgrade-base" \
        bash "$UPGRADE_SH" --project-root "$DUMMY_ROOT" --skip-config-optimisation "$@" \
        > "$log" 2>&1 || rc=$?
    cat "$log"
    if [ "$rc" -eq 0 ]; then
        return 0
    fi
    digest="$(grep -o -- '--skip-reading-confirmation=[0-9a-f]\+' "$log" | tail -n 1)" \
        || fail "upgrade exited $rc without a reading-confirmation digest"
    printf 'NOTE pre-deploy gate asked for the reading confirmation; re-running with %s\n' "$digest" >&2
    HOOKS_DAEMON_UPGRADE_BASE_URL="file:///nonexistent-upgrade-base" \
        bash "$UPGRADE_SH" --project-root "$DUMMY_ROOT" --skip-config-optimisation "$digest" "$@"
}

commit_on_branch() {
    git -C "$WORK/clone" -c user.name=proof -c user.email=proof@example.invalid \
        -c commit.gpgSign=false commit -q --allow-empty -m "$1"
    # Forced: a re-run starts the branch again from main in the bare remote.
    git -C "$WORK/clone" push -q origin "+HEAD:refs/heads/$BRANCH"
    git -C "$BARE" rev-parse "refs/heads/$BRANCH"
}

expect_in() {
    local haystack="$1" needle="$2" what="$3"
    if grep -qF -- "$needle" <<< "$haystack"; then
        ok "$what"
    else
        printf '%s\n' "$haystack" >&2
        fail "$what: expected to find: $needle"
    fi
}

expect_eq() {
    if [ "$1" = "$2" ]; then
        ok "$3 ($1)"
    else
        fail "$3: got '$1', expected '$2'"
    fi
}

# --- the proof --------------------------------------------------------------

rm -rf "$WORK"
mkdir -p "$WORK"
git clone -q "$BARE" "$WORK/clone"
git -C "$WORK/clone" checkout -q -b "$BRANCH" origin/main

step "0. start: a release install from the bare remote"
if [ "$(state stamp)" != "$TAG" ]; then
    printf 'NOTE a previous run left a non-release install; returning to %s first\n' "$TAG"
    upgrade --release
fi
expect_eq "$(state stamp)" "$TAG" "installed stamp is the release tag"
expect_eq "$(git -C "$DAEMON_DIR" rev-parse HEAD)" "$(git -C "$BARE" rev-parse "$TAG^{commit}")" \
    "daemon dir is on the tag"

step "1. track $BRANCH"
FIRST="$(commit_on_branch "proof: first tip of the tracked branch")"
HOOKS_DAEMON_UNSAFE_TRACK_REF="$BRANCH" \
    HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE="Plan 00594 Task 5.1 fixture proof" upgrade
expect_eq "$(git -C "$DAEMON_DIR" rev-parse HEAD)" "$FIRST" "daemon dir is on the branch tip"
expect_eq "$(state tracked_ref)" "$BRANCH" "tracked_ref recorded"
expect_eq "$(state tracked_sha)" "$FIRST" "tracked_sha recorded"
expect_eq "$(state last_release_tag)" "$TAG" "last_release_tag recorded"

step "2. report: not moved"
OUT="$(report "$BARE")"
printf '%s\n' "$OUT"
expect_in "$OUT" "Tracked ref $BRANCH has not moved since ${FIRST:0:7}" "unmoved ref reported"
expect_in "$OUT" "To return to $TAG in one step" "way back names the release"

step "3. move $BRANCH on the remote"
SECOND="$(commit_on_branch "proof: the tracked branch moves")"
OUT="$(report "$BARE")"
printf '%s\n' "$OUT"
expect_in "$OUT" "tracked ref $BRANCH moved ${FIRST:0:7}..${SECOND:0:7}" "move reported"

step "4. failed listing"
OUT="$(report "/nonexistent/branch-channel-remote.git")"
printf '%s\n' "$OUT"
expect_in "$OUT" "Tracked ref $BRANCH: not checked (the remote could not be read)." \
    "failed listing is 'not checked', never 'current'"

step "5. re-track (follow the move)"
HOOKS_DAEMON_UNSAFE_TRACK_REF="$BRANCH" \
    HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE="Plan 00594 Task 5.1 fixture proof" upgrade
expect_eq "$(git -C "$DAEMON_DIR" rev-parse HEAD)" "$SECOND" "daemon dir follows the move"
expect_eq "$(state tracked_sha)" "$SECOND" "tracked_sha follows the move"
expect_eq "$(state last_release_tag)" "$TAG" "last_release_tag kept across re-track"
OUT="$(report "$BARE")"
expect_in "$OUT" "Tracked ref $BRANCH has not moved since ${SECOND:0:7}" "re-tracked ref reported current"

step "6. one-step return: upgrade.sh --release"
upgrade --release
expect_eq "$(git -C "$DAEMON_DIR" rev-parse HEAD)" "$(git -C "$BARE" rev-parse "$TAG^{commit}")" \
    "daemon dir is back on the tag"
expect_eq "$(state stamp)" "$TAG" "stamp is the release again"
expect_eq "$(state tracked_ref)" "" "tracked_ref cleared"
expect_eq "$(state last_release_tag)" "" "last_release_tag cleared"

step "7. pin a full sha, then return"
HOOKS_DAEMON_UNSAFE_TRACK_REF="$FIRST" \
    HOOKS_DAEMON_UNSAFE_TRACK_REF_BECAUSE="Plan 00594 Task 5.1 fixture proof (sha pin)" upgrade
expect_eq "$(git -C "$DAEMON_DIR" rev-parse HEAD)" "$FIRST" "daemon dir is on the pinned sha"
expect_eq "$(state tracked_ref)" "$FIRST" "the pin is recorded as the ref"
OUT="$(report "/nonexistent/branch-channel-remote.git")"
printf '%s\n' "$OUT"
expect_in "$OUT" "Pinned to commit ${FIRST:0:7}; a pin never moves." "a pin is never listed"
upgrade --release
expect_eq "$(state stamp)" "$TAG" "back on the release after the pin"

step "ALL STEPS PASSED"
