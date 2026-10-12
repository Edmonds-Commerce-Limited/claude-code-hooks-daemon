#!/bin/bash
#
# DAEMON-OWNED FILE - do not edit. Deployed into your project by the
# claude-code-hooks-daemon installer and refreshed on every upgrade, so local
# changes are discarded. See CLAUDE/LLM-INSTALL.md, "Which Files Under
# .claude/ Are Yours?", for the full list and the linter exclusions.
#
# Claude Code Hooks Daemon - Provision a fresh checkout (Plan 00477)
#
# A fresh clone of a project that uses the daemon carries the tracked assets
# (hook forwarders, init.sh, settings.json, hooks-daemon.yaml) but not the
# daemon itself: .claude/hooks-daemon/ is gitignored and per-checkout. This
# script builds that local part, at EXACTLY the version the project names, and
# starts the daemon. It is tracked so that it exists before the daemon does.
#
# Usage:
#   bash .claude/provision.sh [--skip-reading-confirmation=<digest>]
#
# What it does:
#   1. Resolves the expected version: daemon.expected_version in
#      .claude/hooks-daemon.yaml, else the .claude/HOOKS-DAEMON.md header.
#      Unknown or malformed: it stops and says so. It never guesses, and it
#      never installs main.
#   2. Fetches that one TAG (vX.Y.Z, depth 1) into .claude/hooks-daemon/.
#   3. Builds the venv through the clone own venv build path and lock
#      (scripts/venv_bootstrap.sh repair).
#   4. Starts the daemon through init.sh, as a hook would.
#
# A clone that is already there is SYNCED to the expected version instead
# (a pull changed daemon.expected_version, so the gitignored clone is behind or
# ahead of it): the same tag fetch and version check, then the target
# release's own pre-deploy gate (the one upgrade runs; it may stop for the
# reading list, and --skip-reading-confirmation=<digest> confirms it), the
# venv rebuild and a restart through the clone own bin/hooks-daemon. A clone
# already at the version is left alone. A failure after the checkout puts the
# previous commit and its venv back and restarts the old daemon.
#
# What it never does:
#   - write a tracked file (everything it creates is under the gitignored
#     .claude/hooks-daemon/);
#   - take the clone URL from the environment or from project config: the URL
#     is the constant below, the same one install.sh trusts;
#   - keep a fetched tag whose version.py does not name the version asked for;
#   - replace a modified clone: one with tracked changes, files outside
#     untracked/, a foreign origin or no git checkout is refused untouched. A
#     clean one is synced, never replaced;
#   - run config migrations or regenerate docs: moving a PROJECT to a new
#     version is upgrade, which also writes the tracked files.
#
# Hooks never run this. A person or an agent runs it, deliberately.
#

set -euo pipefail

# The trusted clone source. Keep equal to DAEMON_REPO in install.sh (a test
# asserts it). Deliberately not overridable.
readonly PROVISION_REPO_URL="https://github.com/Edmonds-Commerce-Limited/claude-code-hooks-daemon.git"

_provision_say() {
    printf '%s\n' "$*"
}

_provision_fail() {
    printf 'PROVISION FAILED: %s\n' "$1" >&2
    shift
    local line
    for line in "$@"; do
        printf '  %s\n' "$line" >&2
    done
    exit 1
}

# The caller confirms it has read the target release's pre-deploy gate listing
# with --skip-reading-confirmation=<digest>, the digest the stop printed. A bare
# flag is passed on as an empty acknowledgement, which matches no listing.
READING_ACKNOWLEDGED=false
READING_ACKNOWLEDGEMENT=""
for _provision_arg in "$@"; do
    case "$_provision_arg" in
        --skip-reading-confirmation=*)
            READING_ACKNOWLEDGED=true
            READING_ACKNOWLEDGEMENT="${_provision_arg#*=}"
            ;;
        --skip-reading-confirmation)
            READING_ACKNOWLEDGED=true
            READING_ACKNOWLEDGEMENT=""
            ;;
        *)
            _provision_fail "unknown argument: $_provision_arg" \
                "Usage: bash .claude/provision.sh [--skip-reading-confirmation=<digest>]"
            ;;
    esac
done

_PROVISION_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PROVISION_PROJECT_ROOT="$(dirname "$_PROVISION_SCRIPT_DIR")"

[[ "$(basename "$_PROVISION_SCRIPT_DIR")" == ".claude" ]] ||
    _provision_fail "this script must live in the project .claude/ directory (found in $_PROVISION_SCRIPT_DIR)"

# The daemon own repository is set up by scripts/bootstrap-self-install.sh, and
# sourcing init.sh there would report the unconfigured repository instead.
if [[ -f "$_PROVISION_PROJECT_ROOT/src/claude_code_hooks_daemon/version.py" ]]; then
    _provision_fail "this is the hooks-daemon repository itself, not a project that uses it." \
        "Set it up for development with: scripts/bootstrap-self-install.sh"
fi

[[ -f "$_PROVISION_SCRIPT_DIR/init.sh" ]] ||
    _provision_fail "$_PROVISION_SCRIPT_DIR/init.sh is missing." \
        "It is a tracked file of the project; restore it from git, then run this again."

command -v git > /dev/null ||
    _provision_fail "git is not installed." "Install git, then run this again."

# init.sh supplies the ONE version resolver and the clone-state probes. Sourcing
# it creates the empty .claude/hooks-daemon/untracked/ skeleton, which is
# expected and handled below.
# shellcheck source=init.sh
source "$_PROVISION_SCRIPT_DIR/init.sh"

DAEMON_DIR="$HOOKS_DAEMON_ROOT_DIR"
if [[ "$DAEMON_DIR" != "$PROJECT_PATH/.claude/hooks-daemon" ]]; then
    _provision_fail "the daemon root is overridden to $DAEMON_DIR (HOOKS_DAEMON_ROOT_DIR)." \
        "Provision only builds the standard location, $PROJECT_PATH/.claude/hooks-daemon."
fi

# ------------------------------------------------------------------
# Step 1: which version?
# ------------------------------------------------------------------
if ! _resolve_expected_version; then
    if [[ "$_HOOKS_DAEMON_EXPECTED_VERSION_SOURCE" == "config-invalid" ]]; then
        _provision_fail "daemon.expected_version in .claude/hooks-daemon.yaml is not X.Y.Z." \
            "It must be a released version such as 3.68.0 (no v prefix, no branch name)." \
            "Correct it in that file, commit it, then run this again."
    fi
    _provision_fail "the daemon version this project expects is unknown." \
        "Neither daemon.expected_version in .claude/hooks-daemon.yaml nor the" \
        "  .claude/HOOKS-DAEMON.md header names one, and provision will not guess." \
        "Ask whoever maintains the project, or set daemon.expected_version to the" \
        "  released version the project was last upgraded to, commit it, and run this again."
fi
VERSION="$_HOOKS_DAEMON_EXPECTED_VERSION"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
    _provision_fail "refusing to use $VERSION as a git tag: it is not X.Y.Z."
TAG="v$VERSION"

_provision_say "Provisioning the hooks daemon $TAG for this checkout (version from $_HOOKS_DAEMON_EXPECTED_VERSION_SOURCE)."

# ------------------------------------------------------------------
# Syncing a clone that is already here (Plan 00477 Task 5.2a)
# ------------------------------------------------------------------
# The same gate, python floor and time limit scripts/upgrade_version.sh uses.
readonly GATE_PYTHON_FLOOR="3.11"
readonly GATE_TIMEOUT_SECONDS=300
readonly GATE_NEEDS_ACKNOWLEDGEMENT=3
readonly SYNC_STAMP_FILE=".daemon-version"

# How far a sync has got: fetched (nothing in the clone moved), checked-out,
# venv (the venv build has started), restart (the daemon restart has started).
SYNC_PHASE="fetched"
PRESENT_VERSION=""
PREVIOUS_COMMIT=""
PREVIOUS_CHECKOUT=""
TAG_KNOWN_BEFORE=false
# The clone's own venv, and where it is set aside while the target's is built:
# the build replaces it in place, so a failed one would otherwise leave none.
SYNC_VENV_DIR=""
SYNC_VENV_BACKUP=""

_provision_clone_git() {
    git -C "$DAEMON_DIR" "$@"
}

# The version a version.py text names, by the rule init.sh applies to the file
# (_clone_version).
_provision_version_in_text() {
    local line
    line="$(grep -m1 -oE '^__version__ = "[0-9]+\.[0-9]+\.[0-9]+"' <<< "$1")" || return 1
    line="${line#*\"}"
    printf '%s' "${line%\"}"
}

# Refuse before anything in the clone has changed: the reason, the manual route.
_provision_sync_refuse() {
    local reason="$1"
    shift
    _provision_fail "$reason" ${@+"$@"} \
        "The clone was not touched." \
        "To move the whole project to another version, use: /hooks-daemon upgrade" \
        "To have provision build a fresh clone instead, move $DAEMON_DIR aside and run this again."
}

# The checks that decide whether provision may touch this clone at all. Sets
# PREVIOUS_COMMIT and PREVIOUS_CHECKOUT (what to return to).
_provision_sync_preflight() {
    local toplevel real_dir origin dirty line count=0
    local -a shown=()
    if [[ ! -e "$DAEMON_DIR/.git" ]]; then
        _provision_sync_refuse "$DAEMON_DIR is not a git checkout, so there is no version to sync from."
    fi
    if ! toplevel="$(_provision_clone_git rev-parse --show-toplevel)"; then
        _provision_sync_refuse "$DAEMON_DIR is not a git checkout that git can read."
    fi
    real_dir="$(cd "$DAEMON_DIR" && pwd -P)"
    if [[ "$toplevel" != "$real_dir" ]]; then
        _provision_sync_refuse "$DAEMON_DIR is not a git checkout of its own (git sees $toplevel)."
    fi
    if ! origin="$(_provision_clone_git config --get remote.origin.url)"; then
        origin=""
    fi
    if [[ "$origin" != "$PROVISION_REPO_URL" ]]; then
        _provision_sync_refuse "the clone's origin is ${origin:-not set}, not $PROVISION_REPO_URL." \
            "Provision fetches only from that URL, and only into a clone that came from it."
    fi
    if ! dirty="$(_provision_clone_git status --porcelain --untracked-files=all -- . ':(exclude)untracked')"; then
        _provision_sync_refuse "git could not report the state of the clone."
    fi
    if [[ -n "$dirty" ]]; then
        while IFS= read -r line; do
            count=$((count + 1))
            if [[ "$count" -le 10 ]]; then
                shown+=("$line")
            fi
        done <<< "$dirty"
        _provision_sync_refuse "the clone has local changes outside untracked/, and a sync would carry them across versions." \
            "Commit, move or discard them yourself first. Changed ($count):" \
            "${shown[@]}"
    fi
    if SYNC_VENV_DIR="$(_provision_own_venv_dir)"; then
        SYNC_VENV_BACKUP="$DAEMON_DIR/untracked/.sync-backup-$(basename "$SYNC_VENV_DIR")"
        if [[ -e "$SYNC_VENV_BACKUP" ]]; then
            _provision_sync_refuse "an earlier sync left its set-aside venv at $SYNC_VENV_BACKUP." \
                "It may be the only copy of a working venv: inspect it, then move it back or remove it."
        fi
    fi
    if ! PREVIOUS_COMMIT="$(_provision_clone_git rev-parse --verify HEAD)"; then
        _provision_sync_refuse "the clone has no commit checked out."
    fi
    if ! PREVIOUS_CHECKOUT="$(_provision_clone_git symbolic-ref -q --short HEAD)"; then
        PREVIOUS_CHECKOUT="$PREVIOUS_COMMIT"
    fi
}

# The venv the resolver chose, when it is one of this clone's own
# (untracked/venv-*), as a physical path comparison: an override naming another
# interpreter is neither read for a stamp nor moved. Prints the directory.
_provision_own_venv_dir() {
    local venv_dir="${PYTHON_CMD%/bin/*}" venv_real daemon_real
    venv_real="$(cd "$venv_dir" && pwd -P)" || return 1
    daemon_real="$(cd "$DAEMON_DIR" && pwd -P)" || return 1
    case "$venv_real" in
        "$daemon_real"/untracked/venv-*) printf '%s' "$venv_dir" ;;
        *) return 1 ;;
    esac
}

# Forget a tag this sync fetched, so a refused tag leaves no ref behind.
_provision_sync_forget_tag() {
    if [[ "$TAG_KNOWN_BEFORE" == false ]]; then
        if ! _provision_clone_git tag -d "$TAG" > /dev/null; then
            _provision_say "WARNING: could not remove the fetched tag $TAG from the clone's refs."
        fi
    fi
}

# Put the recorded commit back. Returns 1 when it cannot be.
_provision_sync_restore_checkout() {
    _provision_clone_git -c advice.detachedHead=false checkout -q "$PREVIOUS_CHECKOUT"
}

# The target release's own pre-deploy gate, run the way scripts/upgrade_version.sh
# runs it: under env -i, a standard-library-only Python found in a trusted system
# location, a verdict file only this function can write. The FROM side is the
# installed version (the venv stamp, else the clone's version before the sync) and
# the TO side is the target. Exit 0 proceeds, 3 stops for the reading, anything
# else could not decide. A target that predates the gate has none to run, exactly
# as upgrading to it runs none.
_provision_gate() (
    local gate_script="$DAEMON_DIR/src/claude_code_hooks_daemon/install/upgrade_gate_standalone.py"
    local sanitise="$DAEMON_DIR/scripts/install/env_sanitise.sh"
    local discovery="$DAEMON_DIR/scripts/lib/python_discovery.sh"
    if [[ ! -f "$gate_script" ]]; then
        _provision_say "$TAG predates the pre-deploy gate, so there is none to run (upgrading to it runs none either)."
        exit 0
    fi
    if [[ ! -f "$sanitise" || ! -f "$discovery" ]]; then
        printf 'The pre-deploy gate of %s cannot run: scripts/install/env_sanitise.sh or scripts/lib/python_discovery.sh is missing.\n' "$TAG" >&2
        exit 1
    fi
    # shellcheck source=/dev/null
    source "$sanitise"
    # shellcheck source=/dev/null
    source "$discovery"
    local PATH
    PATH="$(_gate_trusted_path)"

    local gate_python env_bin od_bin timeout_bin nonce verdict_dir verdict_file
    if ! gate_python="$(unset HOOKS_DAEMON_PYTHON HOOKS_DAEMON_VENV_PATH; find_latest_python "$GATE_PYTHON_FLOOR" "$DAEMON_DIR/pyproject.toml")"; then
        printf 'No Python %s+ interpreter for the pre-deploy gate in a system location (%s).\n' "$GATE_PYTHON_FLOOR" "$GATE_SAFE_PATH" >&2
        exit 1
    fi
    if ! env_bin="$(_gate_tool env)" || ! od_bin="$(_gate_tool od)"; then
        printf 'The pre-deploy gate needs env and od from a system location (%s).\n' "$GATE_SAFE_PATH" >&2
        exit 1
    fi
    nonce="$("$od_bin" -An -N16 -tx1 /dev/urandom)" || nonce=""
    nonce="${nonce//[[:space:]]/}"
    if [[ -z "$nonce" ]] || ! verdict_dir="$(mktemp -d -p /tmp)"; then
        printf 'Could not set up the pre-deploy gate verdict file (no /dev/urandom, or mktemp failed).\n' >&2
        exit 1
    fi
    verdict_file="$verdict_dir/verdict"

    # The installed side: the venv stamp when the venv is one of this clone own,
    # else the version the clone reported before the checkout.
    local installed_stamp="" venv_dir
    if venv_dir="$(_provision_own_venv_dir)" && [[ -f "$venv_dir/$SYNC_STAMP_FILE" ]]; then
        IFS= read -r installed_stamp < "$venv_dir/$SYNC_STAMP_FILE" || [[ -n "$installed_stamp" ]]
    fi
    local -a gate_args=(
        --daemon-dir "$DAEMON_DIR"
        --project-root "$PROJECT_PATH"
        --to "$TAG"
        --target-stamp "$TAG"
        --target-ref "$TAG"
    )
    if [[ -n "$installed_stamp" ]]; then
        gate_args+=(--installed-stamp "$installed_stamp")
    else
        gate_args+=(--from "$PRESENT_VERSION")
    fi
    if [[ "$READING_ACKNOWLEDGED" == true ]]; then
        gate_args+=(--acknowledgement "$READING_ACKNOWLEDGEMENT")
    fi
    gate_args+=(--verdict-file "$verdict_file" --nonce "$nonce")

    local -a runner=("$env_bin" -i "PATH=$GATE_SAFE_PATH" "LANG=C.UTF-8")
    if [[ -n "${HOME:-}" ]]; then
        runner+=("HOME=$HOME")
    fi
    if timeout_bin="$(_gate_tool timeout)"; then
        runner+=("$timeout_bin" "$GATE_TIMEOUT_SECONDS")
    else
        printf 'No timeout command in a system location, so the gate runs without a time limit.\n' >&2
    fi
    _provision_say "Pre-deploy gate: what moving from v$PRESENT_VERSION to $TAG changes (run by $gate_python) ..."
    local gate_output gate_exit=0
    gate_output="$("${runner[@]}" "$gate_python" -I -S "$gate_script" "${gate_args[@]}" 2>&1)" || gate_exit=$?
    printf '%s\n' "$gate_output" >&2

    # A zero exit counts only with the verdict file this run's nonce heads.
    local nonce_line="" line="" verdict=""
    if [[ -f "$verdict_file" && ! -L "$verdict_file" && -O "$verdict_file" ]]; then
        {
            IFS= read -r nonce_line || nonce_line=""
            while IFS= read -r line; do
                case "$line" in
                    verdict=*) verdict="${line#verdict=}" ;;
                esac
            done
        } < "$verdict_file"
    fi
    rm -rf -- "$verdict_dir"
    if [[ "$gate_exit" -eq 0 ]] && { [[ "$nonce_line" != "nonce=$nonce" ]] || [[ "$verdict" != "proceed" ]]; }; then
        printf 'The pre-deploy gate exited 0 without writing this run verdict; %s did not run the gate.\n' "$gate_python" >&2
        exit 1
    fi
    if [[ "$gate_exit" -eq "$GATE_NEEDS_ACKNOWLEDGEMENT" ]]; then
        if [[ "$gate_output" =~ --skip-reading-confirmation=([^[:space:]]+) ]]; then
            printf 'Read every document listed above, then run:\n  bash .claude/provision.sh --skip-reading-confirmation=%s\n' "${BASH_REMATCH[1]}" >&2
        fi
        exit "$GATE_NEEDS_ACKNOWLEDGEMENT"
    fi
    exit "$gate_exit"
)

# Undo a sync that failed after the checkout and fail loudly: the recorded commit
# back, its venv rebuilt and the old daemon restarted when the sync had got that
# far, and a message that says what failed and that the previous version is back.
_provision_sync_abort() {
    local what="$1"
    shift
    local -a notes=()
    if ! _provision_sync_restore_checkout; then
        printf 'PROVISION FAILED: %s\n' "$what" >&2
        printf '  The previous version v%s could NOT be put back: checking out %s failed.\n' "$PRESENT_VERSION" "$PREVIOUS_CHECKOUT" >&2
        printf '  The clone may be at %s. Restore it by hand: git -C %s checkout %s\n' "$TAG" "$DAEMON_DIR" "$PREVIOUS_CHECKOUT" >&2
        exit 1
    fi
    notes+=("The previous version v$PRESENT_VERSION (commit $PREVIOUS_COMMIT) is checked out again.")
    if [[ "$SYNC_PHASE" == "venv" || "$SYNC_PHASE" == "restart" ]]; then
        if [[ -n "$SYNC_VENV_BACKUP" && -d "$SYNC_VENV_BACKUP" ]]; then
            if rm -rf "$SYNC_VENV_DIR" && mv "$SYNC_VENV_BACKUP" "$SYNC_VENV_DIR"; then
                notes+=("Its venv was put back from the copy set aside before the build.")
            else
                notes+=("WARNING: its venv is at $SYNC_VENV_BACKUP, not $SYNC_VENV_DIR. Move it back by hand.")
            fi
        fi
        if [[ -f "$DAEMON_DIR/scripts/venv_bootstrap.sh" ]] \
            && bash "$DAEMON_DIR/scripts/venv_bootstrap.sh" repair "$DAEMON_DIR"; then
            notes+=("Its venv was verified or rebuilt.")
        else
            notes+=("WARNING: its venv could not be verified or rebuilt. Run: $DAEMON_DIR/bin/hooks-daemon repair")
        fi
        if bash "$DAEMON_DIR/bin/hooks-daemon" restart; then
            notes+=("The previous daemon was restarted.")
        else
            notes+=("WARNING: the previous daemon did not restart. Try: $DAEMON_DIR/bin/hooks-daemon restart")
        fi
    fi
    _provision_fail "$what" ${notes[@]+"${notes[@]}"} "The previous version v$PRESENT_VERSION is back in place. No tracked file was changed."
}

_provision_sync_clone() {
    _provision_say "The daemon clone is at v$PRESENT_VERSION and this project expects $TAG: syncing it."
    _provision_sync_preflight

    _provision_say "Fetching $TAG from $PROVISION_REPO_URL ..."
    if _provision_clone_git rev-parse -q --verify "refs/tags/$TAG^{commit}" > /dev/null; then
        TAG_KNOWN_BEFORE=true
    fi
    if ! _provision_clone_git fetch -q --depth 1 "$PROVISION_REPO_URL" "refs/tags/$TAG:refs/tags/$TAG"; then
        _provision_fail "could not fetch tag $TAG from $PROVISION_REPO_URL." \
            "Check that $TAG is a released version and that this machine can reach the repository." \
            "The clone was not changed."
    fi
    local tag_source tag_version=""
    if ! tag_source="$(_provision_clone_git show "refs/tags/$TAG:src/claude_code_hooks_daemon/version.py")"; then
        _provision_sync_forget_tag
        _provision_fail "tag $TAG has no src/claude_code_hooks_daemon/version.py." \
            "The clone was not changed. Report this: a release tag should name its own version."
    fi
    if ! tag_version="$(_provision_version_in_text "$tag_source")"; then
        tag_version=""
    fi
    if [[ "$tag_version" != "$VERSION" ]]; then
        _provision_sync_forget_tag
        _provision_fail "tag $TAG carries daemon version ${tag_version:-unreadable}, not $VERSION." \
            "The clone was not changed. Report this: a release tag should name its own version."
    fi

    if ! _provision_clone_git -c advice.detachedHead=false checkout -q "refs/tags/$TAG"; then
        _provision_sync_abort "could not check out tag $TAG."
    fi
    SYNC_PHASE="checked-out"

    local gate_status=0
    _provision_gate || gate_status=$?
    if [[ "$gate_status" -eq "$GATE_NEEDS_ACKNOWLEDGEMENT" ]]; then
        if ! _provision_sync_restore_checkout; then
            _provision_fail "stopped for the reading list, but the previous version could not be checked out again." \
                "Restore it by hand: git -C $DAEMON_DIR checkout $PREVIOUS_CHECKOUT"
        fi
        _provision_say ""
        _provision_say "PROVISION STOPPED before changing anything: the target release asks for its reading list to be confirmed."
        _provision_say "The clone is back at v$PRESENT_VERSION; no venv was built and the daemon was not restarted."
        exit "$GATE_NEEDS_ACKNOWLEDGEMENT"
    elif [[ "$gate_status" -ne 0 ]]; then
        _provision_sync_abort "the pre-deploy gate of $TAG could not decide (its output is above)."
    fi

    local bootstrap="$DAEMON_DIR/scripts/venv_bootstrap.sh"
    if [[ ! -f "$bootstrap" ]]; then
        _provision_sync_abort "$TAG predates the venv build driver (scripts/venv_bootstrap.sh)."
    fi
    if [[ -n "$SYNC_VENV_BACKUP" ]] && ! mv "$SYNC_VENV_DIR" "$SYNC_VENV_BACKUP"; then
        _provision_sync_abort "could not set the current venv aside at $SYNC_VENV_BACKUP before building the target's."
    fi
    _provision_say "Building the venv for $TAG (this can take a while on a cold cache) ..."
    SYNC_PHASE="venv"
    if ! bash "$bootstrap" repair "$DAEMON_DIR"; then
        _provision_sync_abort "the venv for $TAG could not be built (the output above says which condition failed)."
    fi
    _provision_say "Restarting the daemon ..."
    SYNC_PHASE="restart"
    if ! bash "$DAEMON_DIR/bin/hooks-daemon" restart; then
        _provision_sync_abort "the daemon did not restart at $TAG."
    fi
    if [[ -n "$SYNC_VENV_BACKUP" ]]; then
        rm -rf "$SYNC_VENV_BACKUP"
    fi

    _provision_say ""
    _provision_say "SYNCED: the hooks daemon moved from v$PRESENT_VERSION to $TAG and was restarted."
    _provision_say "No tracked file was changed."
}

# ------------------------------------------------------------------
# Step 2: is this a fresh checkout?
# ------------------------------------------------------------------
if _daemon_clone_present; then
    # The resolved interpreter must also exist on disk, so it is judged as well
    # as the status of _resolve_python_cmd.
    PYTHON_CMD=""
    if ! _resolve_python_cmd; then
        PYTHON_CMD=""
    fi
    if [[ -n "$PYTHON_CMD" && -f "$PYTHON_CMD" ]]; then
        if ! PRESENT_VERSION="$(_clone_version)"; then
            _provision_fail "a daemon clone is already here, but its version.py cannot be read, so it cannot be compared with $TAG." \
                "Repair it first: $DAEMON_DIR/bin/hooks-daemon repair" \
                "To move the whole project to another version, use: /hooks-daemon upgrade"
        fi
        if [[ "$PRESENT_VERSION" == "$VERSION" ]]; then
            _provision_say "The daemon clone is already at $TAG, the expected version: nothing to do."
            exit 0
        fi
        _provision_sync_clone
        exit 0
    fi
    _provision_fail "a daemon clone is already here, but no venv resolves for this project path." \
        "That is a different repair, and it keeps the clone: run" \
        "  $DAEMON_DIR/bin/hooks-daemon repair" \
        "Then run this again: if the clone is at the wrong version it is synced to $TAG."
fi

# Anything in the daemon directory besides the untracked/ skeleton (or a venv
# under it) is someone work, or a clone too damaged to recognise. Neither is
# ours to overwrite.
_provision_unexpected_entries() {
    local entry
    shopt -s nullglob dotglob
    for entry in "$DAEMON_DIR"/*; do
        [[ "$(basename "$entry")" == "untracked" ]] && continue
        printf '%s\n' "$entry"
    done
    shopt -u nullglob dotglob
}
_PROVISION_UNEXPECTED="$(_provision_unexpected_entries)"
if [[ -n "$_PROVISION_UNEXPECTED" ]] || _daemon_orphan_venv_present; then
    _provision_fail "$DAEMON_DIR is not empty, and is not a clone provision recognises." \
        "Provision never overwrites what it did not create. Inspect it, move it aside" \
        "  if it is disposable, and run this again."
fi

# ------------------------------------------------------------------
# Step 3: fetch exactly the tag
# ------------------------------------------------------------------
# init + fetch rather than clone: the directory already holds the untracked/
# skeleton init.sh made, and clone refuses a non-empty directory. The result is
# the same as a depth 1 clone of the tag: a detached checkout with origin set.
# Removing what this step made is safe because the check above established that
# nothing but the skeleton was there before it.
_provision_abort_clone() {
    local entry
    shopt -s nullglob dotglob
    for entry in "$DAEMON_DIR"/*; do
        [[ "$(basename "$entry")" == "untracked" ]] && continue
        rm -rf "$entry"
    done
    shopt -u nullglob dotglob
}

_provision_say "Fetching $TAG from $PROVISION_REPO_URL ..."
mkdir -p "$DAEMON_DIR"
git -C "$DAEMON_DIR" -c init.defaultBranch=main init -q
git -C "$DAEMON_DIR" remote add origin "$PROVISION_REPO_URL"
if ! git -C "$DAEMON_DIR" fetch -q --depth 1 origin "refs/tags/$TAG:refs/tags/$TAG"; then
    _provision_abort_clone
    _provision_fail "could not fetch tag $TAG from $PROVISION_REPO_URL." \
        "Check that $TAG is a released version and that this machine can reach the repository." \
        "Nothing was installed."
fi
if ! git -C "$DAEMON_DIR" -c advice.detachedHead=false checkout -q "refs/tags/$TAG"; then
    _provision_abort_clone
    _provision_fail "could not check out tag $TAG." "Nothing was installed."
fi

CLONE_VERSION=""
if ! CLONE_VERSION="$(_clone_version)"; then
    CLONE_VERSION=""
fi
if [[ "$CLONE_VERSION" != "$VERSION" ]]; then
    _provision_abort_clone
    _provision_fail "tag $TAG carries daemon version ${CLONE_VERSION:-unreadable}, not $VERSION." \
        "Nothing was installed. Report this: a release tag should name its own version."
fi

# ------------------------------------------------------------------
# Step 4: the venv, through the clone own build path and lock
# ------------------------------------------------------------------
BOOTSTRAP="$DAEMON_DIR/scripts/venv_bootstrap.sh"
if [[ ! -f "$BOOTSTRAP" ]]; then
    _provision_abort_clone
    _provision_fail "$TAG predates the venv build driver (scripts/venv_bootstrap.sh)." \
        "Nothing was installed. Set daemon.expected_version to a newer release, or use /hooks-daemon upgrade."
fi
_provision_say "Building the venv (this can take a while on a cold cache) ..."
if ! bash "$BOOTSTRAP" repair "$DAEMON_DIR"; then
    _provision_fail "the clone is in place at $TAG but its venv could not be built." \
        "The output above says which condition failed. Once fixed, run:" \
        "  $DAEMON_DIR/bin/hooks-daemon repair" \
        "No tracked file was changed."
fi

# ------------------------------------------------------------------
# Step 5: start the daemon, the way a hook would
# ------------------------------------------------------------------
# start_daemon waits until a deadline measured from the start of the script,
# sized for a hook. A build before it would have used that budget up.
_HOOKS_DAEMON_START_DEADLINE=$((SECONDS + 60))
PYTHON_CMD=""
if ! start_daemon; then
    _provision_fail "the clone and venv are in place at $TAG but the daemon did not start." \
        "Try: $DAEMON_DIR/bin/hooks-daemon restart" \
        "Then: $DAEMON_DIR/bin/hooks-daemon logs"
fi

_provision_say ""
_provision_say "PROVISIONED: hooks daemon $TAG is running for this checkout."
_provision_say "No tracked file was changed."
SETTINGS="$PROJECT_PATH/.claude/settings.json"
if [[ -f "$SETTINGS" ]] && grep -q '\.claude/hooks/' "$SETTINGS"; then
    _provision_say "No session restart is needed: the hooks are already registered in"
    _provision_say ".claude/settings.json, and the next tool call reaches the running daemon."
else
    _provision_say "WARNING: .claude/settings.json does not register the hooks, so nothing will"
    _provision_say "call this daemon yet. That file is tracked and belongs to the project;"
    _provision_say "restore it from git or ask whoever maintains the project."
fi
