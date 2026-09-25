#!/bin/bash
#
# env_sanitise.sh - Layer 2 entry: reset the ambient environment (Plan 00376
# review2 MAJOR 1)
#
# Layer 2 (scripts/upgrade_version.sh) inherits whatever environment its
# caller happens to be in -- Layer 1, or an agent running it directly. Left
# alone, that is a way for the caller to steer the install:
#
#   - BASH_ENV/ENV run arbitrary code the moment any subshell starts
#   - SHELLOPTS/BASHOPTS can turn on command tracing (or worse) before this
#     script's own `set -euo pipefail` line runs
#   - CDPATH/GLOBIGNORE/IFS can misdirect a bare `cd` or word-split a value
#     unexpectedly
#   - PYTHON*/LD_*/DYLD_*/GIT_*/PERL5*/RUBY*/NODE_OPTIONS steer the
#     interpreters and tools the rest of this script and the libraries it
#     sources shell out to
#
# HOME, LANG, proxy variables and uv/cache settings are left alone -- they
# are data the install legitimately needs, not a way to change what code
# runs or which files are read.
#
# This file is sourced FIRST in upgrade_version.sh, before any other
# install/*.sh library, and _sanitise_layer2_env is called immediately
# after. No include guard (review3 MAJOR 2): a pre-exported guard variable
# of this file's name (plus a hostile exported `_gate_tool`) used to skip
# this file's own definitions entirely. Nothing here needs one -- functions
# redefine harmlessly, and `GATE_SAFE_PATH` is a plain assignment, not
# `readonly` -- so sourcing this file always redefines everything.
#
# Usage:
#   source "$(dirname "$0")/env_sanitise.sh"
#   _sanitise_layer2_env
#

# Where the gate and what feeds it take their tools from: fixed system
# locations, never the caller's PATH, so a planted git, awk or python
# cannot answer for any part of Layer 2, not just the pre-deploy gate
# subprocess. A listed LOCATION is not necessarily trusted CONTENT though
# (review2 MAJOR 2): Homebrew's /opt/homebrew/bin and /usr/local/bin are
# user-owned by default on macOS, so `_gate_trusted_path` filters this raw
# list through `_gate_dir_is_trusted` before anything uses it.
# install/upgrade_tasks.py TRUSTED_TOOL_PATH is the same list, with the
# same ownership and permission filter applied by its own `_trusted_dirs`.
GATE_SAFE_PATH="/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin"

# _gate_dir_is_trusted() - True when $1 is root-owned and neither group- nor
# world-writable (review2 MAJOR 2). A GATE_SAFE_PATH entry is a fixed system
# LOCATION, not a fixed system CONTENT: a directory this same process could
# itself write to -- Homebrew's /opt/homebrew/bin and /usr/local/bin are
# user-owned by default on macOS -- is not trusted merely for being listed,
# because that user could plant a tool there. `stat` itself is resolved from
# the unfiltered GATE_SAFE_PATH (not this check), same trust level `env`/`od`
# had before this fix: /usr/bin or /bin, first in that list, ship the real
# one on every host this matters for. An agent running AS root defeats this
# check by construction (root owns every directory here regardless of its
# permission bits); no in-process check can defend against that, and
# LLM-UPDATE says so.
_gate_dir_is_trusted() {
    local PATH="$GATE_SAFE_PATH"
    local dir="$1" owner="" perms=""
    [ -d "$dir" ] || return 1
    owner="$(stat -c '%u' "$dir" 2> /dev/null)" || owner="$(stat -f '%u' "$dir" 2> /dev/null)" || return 1
    [ "$owner" = "0" ] || return 1
    perms="$(stat -c '%a' "$dir" 2> /dev/null)" || perms="$(stat -f '%Lp' "$dir" 2> /dev/null)" || return 1
    case "$perms" in *[!0-7]*) return 1 ;; esac
    [ $(($((8#$perms)) & 8#022)) -eq 0 ]
}

# _gate_trusted_path() - Print GATE_SAFE_PATH with every entry
# `_gate_dir_is_trusted` rejects removed.
_gate_trusted_path() {
    local dir
    local -a dirs
    local -a trusted=()
    IFS=: read -r -a dirs <<< "$GATE_SAFE_PATH"
    for dir in "${dirs[@]}"; do
        _gate_dir_is_trusted "$dir" && trusted+=("$dir")
    done
    local IFS=:
    printf '%s\n' "${trusted[*]}"
}

# _gate_tool() - Print the absolute path of $1 from a trusted GATE_SAFE_PATH
# entry; return 1 when no trusted location has it. Shared by Layer 1 (to
# resolve the `bash`/`env` it launches Layer 2 with) and every function in
# upgrade_version.sh that feeds the gate.
_gate_tool() {
    local dir
    local -a dirs
    IFS=: read -r -a dirs <<< "$(_gate_trusted_path)"
    for dir in "${dirs[@]}"; do
        if [ -x "$dir/$1" ]; then
            printf '%s\n' "$dir/$1"
            return 0
        fi
    done
    return 1
}

# _sanitise_layer2_env() - Reset the class of variables that can steer what
# code Layer 2 runs, or where it looks for its inputs. See the file header
# for the full rationale per family.
_sanitise_layer2_env() {
    # PATH: fixed system locations only -- never the caller's PATH.
    PATH="$(_gate_trusted_path)"
    export PATH

    # Variables a subshell reads to run code before this script's own logic
    # gets a say.
    unset -v BASH_ENV ENV CDPATH GLOBIGNORE NODE_OPTIONS

    # IFS controls word-splitting for every unquoted expansion and every
    # `read` in the libraries this script is about to source; reset it to
    # the bash default rather than merely unsetting it.
    IFS=$' \t\n'

    # SHELLOPTS/BASHOPTS are bash-maintained and READONLY -- `unset` on them
    # errors under `set -e` (they cannot be assigned to either). Neutralise
    # the options they could have primed at shell startup, before this
    # function ever ran, instead of the variable itself: `set +o` always
    # succeeds and re-exports a clean SHELLOPTS from this point on, so no
    # child process this script spawns inherits the option even though this
    # shell's own earliest lines already ran under it.
    set +o xtrace
    set +o verbose

    # PYTHON*/LD_*/DYLD_*/GIT_*/PERL5*/RUBY*: steer the interpreters and
    # tools the rest of this script and the libraries it sources shell out
    # to. The library sets no GIT_* of its own, so none is exempt.
    local _name
    for _name in "${!PYTHON@}" "${!LD_@}" "${!DYLD_@}" "${!GIT_@}" "${!PERL5@}" "${!RUBY@}"; do
        unset -v "$_name"
    done
}
