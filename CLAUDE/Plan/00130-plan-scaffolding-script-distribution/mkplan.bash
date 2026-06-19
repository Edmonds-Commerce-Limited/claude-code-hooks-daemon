#!/usr/bin/env bash
#
# mkplan.bash — scaffold the next numbered plan folder, in this script's own
# directory. Drop it into any hooks-daemon / plan-workflow project's plan
# folder (conventionally CLAUDE/Plan/) and run it from anywhere.
#
# Usage:
#   <plan-dir>/mkplan.bash "descriptive-kebab-name"
#
# Portability model:
#   The script makes plans in ITS OWN directory, resolved from BASH_SOURCE
#   (symlink-safe) — never the current working directory. Wherever the script
#   physically lives IS the plan folder, so it needs no config: that location
#   already is the project's configured plan dir (SSoT stays with the daemon's
#   .claude/hooks-daemon config, which is why the script is placed there).
#
# What it does (fail-fast at every step):
#   1. Requires exactly one non-empty argument: the plan name.
#   2. Normalises + validates the name into a safe kebab slug that starts
#      with a letter (matches the daemon's NNNNN-[a-zA-Z] plan pattern).
#   3. Resolves the next plan number from the git-anchored counter
#      (`hooksdaemon.latestPlanNumber`), bootstrapping from a filesystem
#      scan when the counter is unset — exactly like the hooks daemon does.
#      A brand-new project (no counter, no plans) starts at 00001.
#   4. Sanity-checks the number against the folders on disk and refuses to
#      proceed on drift or collision.
#   5. Creates <plan-dir>/NNNNN-name/ and scaffolds PLAN.md.
#   6. Advances the git counter so the next plan reads counter + 1.
#
# The script is the SOLE writer of the counter when it creates a plan: the
# internal mkdir runs in this subprocess, so the daemon's validate_plan_number
# handler never sees it and never double-increments.

set -euo pipefail

readonly COUNTER_KEY="hooksdaemon.latestPlanNumber"
readonly NUMBER_WIDTH=5
readonly MAX_NAME_LENGTH=80

# --- helpers ---------------------------------------------------------------

die() {
    printf 'mkplan: error: %s\n' "$1" >&2
    exit 1
}

usage() {
    cat >&2 <<'USAGE'
Usage: mkplan.bash "descriptive-kebab-name"

Creates the next sequentially-numbered plan folder (in this script's own
directory) and scaffolds its PLAN.md.

Arguments:
  name   Required. A single non-empty string describing the plan. It is
         normalised to a kebab-case slug and MUST start with a letter.
         Do NOT include a number prefix — the script assigns it.

Examples:
  mkplan.bash "wsdl-patch-pipeline-hardening"
  mkplan.bash "Order despatch retries"   # -> 000NN-Order-despatch-retries
USAGE
}

# Highest existing plan number on disk. Mirrors the daemon's scan:
#   - direct numbered children of CLAUDE/Plan/      (NNNNN-name/)
#   - one level inside non-numbered subdirs         (Completed/NNNNN-name/, archive/...)
# Pattern requires a letter after the hyphen so date dirs (2026-06-19) are ignored.
filesystem_highest() {
    local plan_dir="$1"
    local highest=0 dir base num
    shopt -s nullglob
    for dir in "$plan_dir"/*/ "$plan_dir"/*/*/; do
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
    die "expected exactly one argument (the plan name), got $#"
fi

raw_name="$1"

# Trim surrounding whitespace.
raw_name="${raw_name#"${raw_name%%[![:space:]]*}"}"
raw_name="${raw_name%"${raw_name##*[![:space:]]}"}"

if [[ -z "$raw_name" ]]; then
    die "plan name must be a non-empty string"
fi

# Normalise: whitespace -> hyphen, collapse repeats, trim stray hyphens.
name="${raw_name//[[:space:]]/-}"
while [[ "$name" == *--* ]]; do
    name="${name//--/-}"
done
name="${name#-}"
name="${name%-}"

if [[ -z "$name" ]]; then
    die "plan name normalised to empty — provide letters/digits"
fi

if (( ${#name} > MAX_NAME_LENGTH )); then
    die "plan name too long (${#name} chars, max ${MAX_NAME_LENGTH})"
fi

# Must start with a letter and contain only [A-Za-z0-9-]. This both keeps the
# folder filesystem-safe and satisfies the daemon's NNNNN-[a-zA-Z] convention.
if [[ ! "$name" =~ ^[A-Za-z][A-Za-z0-9-]*$ ]]; then
    die "invalid plan name '$name' — must start with a letter and contain only letters, digits and hyphens (no number prefix, no path separators)"
fi

# --- locate the plan dir (this script's own dir) + the repo ----------------

# Resolve the real directory containing this script, following symlinks, so
# the plan dir is wherever the script physically lives — independent of CWD.
source_path="${BASH_SOURCE[0]}"
while [[ -L "$source_path" ]]; do
    link_dir="$(cd -P "$(dirname "$source_path")" && pwd)"
    source_path="$(readlink "$source_path")"
    [[ "$source_path" == /* ]] || source_path="$link_dir/$source_path"
done
plan_dir="$(cd -P "$(dirname "$source_path")" && pwd)"

# The counter lives in the enclosing repo's git config — resolve it from the
# plan dir (not CWD) so the script works from anywhere, including nested repos.
if ! repo_root="$(git -C "$plan_dir" rev-parse --show-toplevel)"; then
    die "$plan_dir is not inside a git repository — cannot resolve the plan counter"
fi

plan_rel="${plan_dir#"$repo_root"/}"

# --- resolve + sanity-check the next number --------------------------------

fs_highest="$(filesystem_highest "$plan_dir")"

if counter_raw="$(git -C "$repo_root" config --local --get "$COUNTER_KEY")"; then
    if [[ ! "$counter_raw" =~ ^[0-9]+$ ]]; then
        printf 'mkplan: counter %s is non-numeric (%q); bootstrapping from filesystem (%s)\n' \
            "$COUNTER_KEY" "$counter_raw" "$fs_highest" >&2
        counter="$fs_highest"
    else
        counter=$((10#$counter_raw))
    fi
else
    printf 'mkplan: counter %s unset; bootstrapping from filesystem high-water mark (%s)\n' \
        "$COUNTER_KEY" "$fs_highest" >&2
    counter="$fs_highest"
fi

# Drift guard: the git counter is authoritative, but if the filesystem already
# holds a HIGHER number the counter is stale and counter+1 would collide or
# mis-order. Refuse and tell the user how to reconcile.
if (( fs_highest > counter )); then
    die "counter drift: git counter is $counter but disk holds plan $fs_highest. Reconcile with: git -C '$repo_root' config --local $COUNTER_KEY $fs_highest"
fi

next=$((counter + 1))
printf -v padded '%0*d' "$NUMBER_WIDTH" "$next"

# Collision guard: nothing on disk may already carry this number (active or
# archived). filesystem_highest already covers the common case, but check the
# concrete number explicitly for a precise error.
shopt -s nullglob
existing=( "$plan_dir/$padded-"*/ "$plan_dir"/*/"$padded-"*/ )
shopt -u nullglob
if (( ${#existing[@]} > 0 )); then
    die "plan number $padded already exists on disk: ${existing[0]}"
fi

target="$plan_dir/$padded-$name"
if [[ -e "$target" ]]; then
    die "target folder already exists: $target"
fi

# --- create the folder + scaffold PLAN.md ----------------------------------

mkdir "$target"

title="${name//-/ }"
created="$(date +%F)"
plan_file="$target/PLAN.md"

# Owner from git identity, with a portable fallback.
if ! owner="$(git -C "$repo_root" config user.name)" || [[ -z "$owner" ]]; then
    owner="Unknown"
fi

cat > "$plan_file" <<PLAN
# Plan $padded: $title

**Status**: Not Started
**Created**: $created
**Owner**: $owner
**Priority**: Medium

## Overview

<!-- 2-3 paragraphs: what this plan achieves and why. -->

## Goals

- <!-- clear, measurable goal -->

## Non-Goals

- <!-- what this plan will NOT do -->

## Tasks

### Phase 1: <!-- phase name -->

- [ ] ⬜ **Task 1.1**: <!-- description -->

## Success Criteria

- [ ] <!-- criterion that must be met -->

## Notes & Updates

### $created

- Plan scaffolded.
PLAN

# --- advance the counter (only after a successful write) -------------------

git -C "$repo_root" config --local "$COUNTER_KEY" "$next"

# --- report ----------------------------------------------------------------

rel_target="${target#"$repo_root"/}"
cat >&2 <<DONE
mkplan: created plan $padded
  folder: $rel_target/
  plan:   $rel_target/PLAN.md
  counter $COUNTER_KEY -> $next

Next steps (not done automatically):
  - Fill in PLAN.md (overview, goals, tasks).
  - Add a row to $plan_rel/README.md under "Active Plans" (if the project keeps one).
DONE

printf '%s\n' "$target"
