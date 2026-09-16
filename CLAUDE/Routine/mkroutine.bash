#!/usr/bin/env bash
#
# mkroutine.bash — scaffold the next numbered Routine folder, in this script's
# own directory (conventionally CLAUDE/Routine/).
#
# Usage:
#   <routine-dir>/mkroutine.bash "descriptive-kebab-name"
#
# A Plan finishes; a Routine recurs. So a Routine folder holds a definition
# (ROUTINE.md) plus a RUNS/ directory of per-year append-only ledgers — one row
# per run — rather than a completion. See CLAUDE/Plan/00412's DESIGN.md.
#
# Why this mirrors mkplan.bash instead of sharing code with it:
#   mkplan.bash documents self-containment as a design property — it is
#   deployed standalone into client projects by the installer, so a sourced
#   library would break the thing that makes it deployable. The numbering
#   algorithm is therefore duplicated ON PURPOSE, and the cost is paid in
#   tests/unit/scripts/test_mkroutine_scaffolder.py, which pins the properties
#   the two must agree on so a fix applied to one and not the other fails.
#
# This script is NOT deployed to client projects. The Routine concept has no
# run CLI, no QA checks and no overdue assertion yet (Plan 00412 Tasks 2.3-2.5);
# shipping the scaffolder first would put half a feature in other people's
# repositories.
#
# What it does (fail-fast at every step):
#   1. Requires exactly one non-empty argument: the routine name.
#   2. Normalises + validates the name into a safe kebab slug starting with a
#      letter.
#   3. Takes an exclusive, portable lock on the routine dir so concurrent runs
#      cannot assign the same number.
#   4. Resolves the next number from the git-anchored counter
#      (`hooksdaemon.latestRoutineNumber`) — its OWN key, never the plan
#      counter — bootstrapping from a filesystem scan when it is unset.
#   5. Refuses to proceed on counter drift or a number collision.
#   6. Creates <routine-dir>/NNNNN-name/ with ROUTINE.md and an empty RUNS/.
#   7. Advances the counter so the next routine reads counter + 1.

set -euo pipefail

readonly COUNTER_KEY="hooksdaemon.latestRoutineNumber"
readonly NUMBER_WIDTH=5
readonly MAX_NAME_LENGTH=80
readonly LOCK_BASENAME=".mkroutine.lock"
readonly LOCK_MAX_ATTEMPTS=100
readonly LOCK_RETRY_SECONDS=0.1
readonly RUNS_DIR_BASENAME="RUNS"
readonly TEMPLATE_BASENAME="_TEMPLATE_.md"

# Populated once the lock is held, so the EXIT trap only ever removes a lock
# this process actually owns (never another runner's lock on a timeout-die).
lock_held=""

# --- helpers ---------------------------------------------------------------

die() {
    printf 'mkroutine: error: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat >&2 <<'USAGE'
Usage: mkroutine.bash "descriptive-kebab-name"

Creates the next sequentially-numbered Routine folder (in this script's own
directory, or $MKROUTINE_ROUTINE_DIR if set), scaffolds its ROUTINE.md and
creates an empty RUNS/ for its per-year run ledgers.

Arguments:
  name   Required. A single non-empty string describing the routine. It is
         normalised to a kebab-case slug and MUST start with a letter.
         Do NOT include a number prefix — the script assigns it.

Environment:
  MKROUTINE_ROUTINE_DIR   Optional. Absolute path to the routine dir.
                          Overrides self-location.

Examples:
  mkroutine.bash "backup-restore-drill"
  mkroutine.bash "Dependency audit"   # -> 000NN-Dependency-audit
USAGE
}

# Release the routine-dir lock. Only removes the lock if THIS process took it
# (lock_held set) and the dir is still present — never another runner's lock.
release_lock() {
    if [[ -n "$lock_held" && -d "$lock_held" ]]; then
        rmdir "$lock_held"
    fi
}

# Acquire an exclusive lock via atomic `mkdir`. Portable (Linux + macOS/BSD, no
# `flock` dependency) and silent: mkdir's stderr is captured into a variable,
# NOT discarded, and surfaced only if we time out.
acquire_lock() {
    local lock_dir="$1"
    local attempts=0 err
    while ! err="$(mkdir "$lock_dir" 2>&1)"; do
        attempts=$((attempts + 1))
        if (( attempts >= LOCK_MAX_ATTEMPTS )); then
            die "timed out acquiring routine lock '$lock_dir' (concurrent run, or a stale lock — remove the directory if no other mkroutine is running). Last error: $err"
        fi
        sleep "$LOCK_RETRY_SECONDS"
    done
    lock_held="$lock_dir"
    trap release_lock EXIT INT TERM
}

# Highest existing routine number on disk:
#   - direct numbered children of the routine dir   (NNNNN-name/)
#   - one level inside non-numbered subdirs         (Completed/NNNNN-name/)
# The second is what a naive top-level scan misses, and missing it is how an
# archived routine's number gets handed out a second time.
# Pattern requires a letter after the hyphen so date dirs (2026-06-19) are
# ignored. Dotfiles (e.g. the lock dir) are not matched by the unquoted globs.
filesystem_highest() {
    local routine_dir="$1"
    local highest=0 dir base num
    shopt -s nullglob
    for dir in "$routine_dir"/*/ "$routine_dir"/*/*/; do
        base="$(basename "$dir")"
        if [[ "$base" =~ ^([0-9]{1,5})-[a-zA-Z] ]]; then
            num=$((10#${BASH_REMATCH[1]}))
            if (( num > highest )); then
                highest=$num
            fi
        fi
    done
    shopt -u nullglob
    printf '%d' "$highest"
}

# --- argument handling -----------------------------------------------------

if [[ $# -eq 1 ]] && { [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; }; then
    usage
    exit 0
fi

if [[ $# -ne 1 ]]; then
    usage
    die "expected exactly one argument (the routine name), got $#"
fi

raw_name="$1"

# Trim surrounding whitespace.
raw_name="${raw_name#"${raw_name%%[![:space:]]*}"}"
raw_name="${raw_name%"${raw_name##*[![:space:]]}"}"

if [[ -z "$raw_name" ]]; then
    die "routine name must be a non-empty string"
fi

# Normalise: whitespace -> hyphen, collapse repeats, trim stray hyphens.
name="${raw_name//[[:space:]]/-}"
while [[ "$name" == *--* ]]; do
    name="${name//--/-}"
done
name="${name#-}"
name="${name%-}"

if [[ -z "$name" ]]; then
    die "routine name normalised to empty — provide letters/digits"
fi

if (( ${#name} > MAX_NAME_LENGTH )); then
    die "routine name too long (${#name} chars, max ${MAX_NAME_LENGTH})"
fi

# Must start with a letter and contain only [A-Za-z0-9-]. Keeps the folder
# filesystem-safe and matches the NNNNN-[a-zA-Z] convention the scans rely on.
if [[ ! "$name" =~ ^[A-Za-z][A-Za-z0-9-]*$ ]]; then
    die "invalid routine name '$name' — must start with a letter and contain only letters, digits and hyphens (no number prefix, no path separators)"
fi

# --- locate the routine dir (override, else this script's own dir) ----------

if [[ -n "${MKROUTINE_ROUTINE_DIR:-}" ]]; then
    [[ -d "$MKROUTINE_ROUTINE_DIR" ]] || die "MKROUTINE_ROUTINE_DIR is set but not a directory: $MKROUTINE_ROUTINE_DIR"
    routine_dir="$(cd -P "$MKROUTINE_ROUTINE_DIR" && pwd)"
else
    # Resolve the real directory containing this script, following symlinks, so
    # routines land wherever the script physically lives — independent of CWD.
    source_path="${BASH_SOURCE[0]}"
    while [[ -L "$source_path" ]]; do
        link_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
        source_path="$(readlink "$source_path")"
        [[ "$source_path" == /* ]] || source_path="$link_dir/$source_path"
    done
    routine_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
fi

# The counter lives in the enclosing repo's git config — resolve it from the
# routine dir (not CWD) so the script works from anywhere, including nested
# repos.
if ! repo_root="$(git -C "$routine_dir" rev-parse --show-toplevel)"; then
    die "$routine_dir is not inside a git repository — cannot resolve the routine counter"
fi

routine_rel="${routine_dir#"$repo_root"/}"

# --- take the lock, then resolve + sanity-check the next number ------------

# Everything from here to the counter write is the critical section: a single
# atomic-mkdir lock serialises concurrent runners so no two assign the same N.
acquire_lock "$routine_dir/$LOCK_BASENAME"

fs_highest="$(filesystem_highest "$routine_dir")"

if counter_raw="$(git -C "$repo_root" config --local --get "$COUNTER_KEY")"; then
    if [[ ! "$counter_raw" =~ ^[0-9]+$ ]]; then
        printf 'mkroutine: counter %s is non-numeric (%q); bootstrapping from filesystem (%s)\n' \
            "$COUNTER_KEY" "$counter_raw" "$fs_highest" >&2
        counter="$fs_highest"
    else
        counter=$((10#$counter_raw))
    fi
else
    printf 'mkroutine: counter %s unset; bootstrapping from filesystem high-water mark (%s)\n' \
        "$COUNTER_KEY" "$fs_highest" >&2
    counter="$fs_highest"
fi

# Drift guard: the git counter is authoritative, but if the filesystem already
# holds a HIGHER number the counter is stale and counter+1 would collide or
# mis-order. Refuse and state how to reconcile.
if (( fs_highest > counter )); then
    die "counter ($counter) is behind the highest routine on disk ($fs_highest). The counter is stale; reconcile with: git -C '$repo_root' config --local $COUNTER_KEY $fs_highest"
fi

next=$((counter + 1))
printf -v padded '%0*d' "$NUMBER_WIDTH" "$next"

# Collision guard: nothing on disk may already carry this number (active or
# archived). filesystem_highest covers the common case; check the concrete
# number explicitly for a precise error.
shopt -s nullglob
existing=( "$routine_dir/$padded-"*/ "$routine_dir"/*/"$padded-"*/ )
shopt -u nullglob
if (( ${#existing[@]} > 0 )); then
    die "routine number $padded already exists on disk: ${existing[0]}"
fi

target="$routine_dir/$padded-$name"
if [[ -e "$target" ]]; then
    die "target folder already exists: $target"
fi

# --- create the folder + scaffold ROUTINE.md -------------------------------

if ! mkdir "$target"; then
    die "could not create routine folder '$target' (permissions, or a concurrent run won the race)"
fi

title="${name//-/ }"
created="$(date +%F)"
routine_file="$target/ROUTINE.md"

# Owner from git identity, with a portable fallback.
if ! owner="$(git -C "$repo_root" config user.name)" || [[ -z "$owner" ]]; then
    owner="Unknown"
fi

# Project-managed template, mirroring mkplan.bash: when the routine dir carries
# a tracked _TEMPLATE_.md, render it with pure-bash placeholder substitution.
# Without one, fall back to the built-in skeleton so the script stays
# self-contained.
template_file="$routine_dir/$TEMPLATE_BASENAME"
if [[ -f "$template_file" ]]; then
    if ! body="$(cat "$template_file")"; then
        die "could not read routine template '$template_file'"
    fi
    body="${body//\{\{ROUTINE_NUMBER\}\}/$padded}"
    body="${body//\{\{ROUTINE_TITLE\}\}/$title}"
    body="${body//\{\{CREATED_DATE\}\}/$created}"
    body="${body//\{\{OWNER\}\}/$owner}"
    printf '%s\n' "$body" > "$routine_file"
else
cat > "$routine_file" <<ROUTINE
# Routine $padded: $title

**Status**: Active
**Created**: $created
**Owner**: $owner
**Trigger**: <!-- schedule | session_start | release -->
**Period**: <!-- e.g. 30 days. Only for a schedule trigger. -->
**Grace**: <!-- e.g. 7 days. Omit to take a fifth of the period. -->

<!-- Leave the placeholders above until you have DECIDED. They parse as
     "not declared", which is honest and which the QA sweep reports; filling
     in a plausible cadence nobody chose would be silently wrong instead. -->

## Purpose

<!-- What recurring obligation this discharges, and what goes wrong if it
     stops happening. -->

## Scope

<!-- What each run covers. If runs can be full or delta, say which checks are
     delta-able and which are full-only: a delta run is structurally blind to
     a class of finding, which is what makes the periodic full run a
     compensating control rather than belt-and-braces. -->

## Procedure

<!-- The steps a run performs. Written for whoever executes it, including an
     agent that has never seen this routine before. -->

## What a run records

Every run appends one row to \`$RUNS_DIR_BASENAME/<year>.md\`, covering:

- the interval it covered, \`from -> to\` (a commit or tag at each end) —
  never a mutable "last run" pointer, so a gap between runs stays detectable;
- the outcome, including \`no findings\`, which is recorded as distinctly as a
  run that found something and is NOT the same as never having run;
- for a delta run, which checks it did NOT perform.

## Non-Goals

- <!-- what this routine will NOT do -->
ROUTINE
fi

# --- scaffold RUNS/ --------------------------------------------------------

# Created up front and left empty, deliberately: "the routine has never run"
# and "nobody ever made the runs directory" are different facts, and only the
# first is interesting. With RUNS/ always present, an empty one always means
# never ran.
runs_dir="$target/$RUNS_DIR_BASENAME"
if ! mkdir "$runs_dir"; then
    die "could not create runs folder '$runs_dir'"
fi

# --- advance the counter (only after a successful write) -------------------

# High-water-mark write: the lock guarantees `next` is monotonic, and max() is
# belt-and-braces against ever lowering the counter.
new_counter="$next"
if (( counter > new_counter )); then
    new_counter="$counter"
fi
git -C "$repo_root" config --local "$COUNTER_KEY" "$new_counter"

# Lock is released by the EXIT trap (release_lock).

# --- report ----------------------------------------------------------------

rel_target="${target#"$repo_root"/}"
cat >&2 <<DONE
mkroutine: created routine $padded
  folder:  $rel_target/
  routine: $rel_target/ROUTINE.md
  runs:    $rel_target/$RUNS_DIR_BASENAME/
  counter $COUNTER_KEY -> $new_counter

Next steps (not done automatically):
  - Fill in ROUTINE.md (purpose, scope, procedure, trigger).
  - Add a row to $routine_rel/README.md under "Active Routines".
DONE

printf '%s\n' "$target"
