#!/bin/bash
# Acquire the host-wide full-QA lock (Plan 00463), or give up after a bound
# wait naming the pid(s) currently holding it (review 10 m1).
#
# A plain `flock "${FD}"` (no `-w`) waits FOREVER. Review 10's H repro shows
# why that is dangerous, not merely slow: a holder that backgrounds an orphan
# process before exiting leaves that orphan holding the SAME inherited,
# non-CLOEXEC descriptor -- the kernel only releases a lock when every
# descriptor referencing it closes, and an orphan can outlive the run that
# spawned it indefinitely. An unbounded waiter then blocks forever with no
# diagnostic, and the only way out is for someone to notice and kill it by
# hand. A bounded wait turns that into an actionable failure.
#
# Usage (after `set -euo pipefail`):
#   source ".../acquire_full_qa_lock.bash"
#   acquire_full_qa_lock_or_die "${FULL_QA_LOCK}"
# On success `FULL_QA_LOCK_FD` is open and locked, inherited by every further
# child of this shell for free (an ordinary, non-CLOEXEC descriptor from
# `exec {FD}>>`). On failure the function exits the CALLING shell (not just
# itself) with a message naming the holding pid(s), found via /proc.

: "${FULL_QA_LOCK_WAIT_SECONDS:=600}"

# Every pid with an open fd resolving to "$1", one per line, numerically
# sorted and de-duplicated. Best-effort: a fd that races away between the
# glob and the readlink is skipped explicitly (matches full_qa_lock.py's own
# treatment of the same race), never treated as evidence either way.
_full_qa_lock_holders() {
    local lock_file="$1" fd_link target pid
    local -a pids=()
    for fd_link in /proc/[0-9]*/fd/*; do
        if [ ! -e "${fd_link}" ]; then
            continue
        fi
        if ! target="$(readlink -f "${fd_link}" 2>/dev/null)"; then
            continue
        fi
        if [ "${target}" != "${lock_file}" ]; then
            continue
        fi
        pid="${fd_link#/proc/}"
        pid="${pid%%/*}"
        pids+=("${pid}")
    done
    if [ "${#pids[@]}" -eq 0 ]; then
        return 0
    fi
    printf '%s\n' "${pids[@]}" | sort -un
}

# Succeeds when FULL_QA_LOCK_INHERITED_FD names an inherited descriptor that
# resolves to "$1" AND whose open file description holds (or can take) the
# lock: `flock -n` on that very descriptor. The variable is only a HINT at
# which descriptor to test; the proof is the flock, so a variable naming an
# unrelated or unlocked-by-us descriptor proves nothing.
_full_qa_lock_inherited() {
    local lock_file="$1" fd="${FULL_QA_LOCK_INHERITED_FD:-}" target
    if [[ ! "${fd}" =~ ^[0-9]+$ ]]; then
        return 1
    fi
    if ! target="$(readlink -f "/proc/self/fd/${fd}" 2>/dev/null)"; then
        return 1
    fi
    if [ "${target}" != "$(readlink -f "${lock_file}")" ]; then
        return 1
    fi
    flock -n "${fd}" || return 1
    FULL_QA_LOCK_FD="${fd}"
}

acquire_full_qa_lock_or_die() {
    local lock_file="$1" holders
    if _full_qa_lock_inherited "${lock_file}"; then
        return 0
    fi
    exec {FULL_QA_LOCK_FD}>>"${lock_file}"
    if flock -w "${FULL_QA_LOCK_WAIT_SECONDS}" "${FULL_QA_LOCK_FD}"; then
        return 0
    fi
    holders="$(_full_qa_lock_holders "${lock_file}")"
    echo "acquire_full_qa_lock_or_die: gave up waiting for the host-wide" \
        "full-QA lock after ${FULL_QA_LOCK_WAIT_SECONDS}s: ${lock_file}" >&2
    if [ -n "${holders}" ]; then
        echo "  Held by pid(s): $(echo "${holders}" | tr '\n' ' ')" >&2
    else
        echo "  Could not identify the holding pid(s) (they may have" \
            "exited already, or /proc is unreadable)." >&2
    fi
    exit 1
}
