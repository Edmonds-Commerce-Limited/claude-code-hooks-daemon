# Plan 00443: acceptance skip reason names the overflow

**Status**: Complete
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

`tests/acceptance/conftest.py` skips the whole acceptance suite when it finds
no socket under `untracked/`, with the reason "Daemon not running — start with:
`./bin/hooks-daemon restart`". In a worktree that reason is wrong, and wrong in
the most expensive direction: the daemon IS running, and restarting it produces
exactly the same skip. Its socket is not under `untracked/` because the natural
path exceeded the 104-byte AF_UNIX limit and `get_socket_path` fell back to
`/tmp`.

The suite already has everything needed to tell the two apart.
`prospective_socket_path` builds the path a daemon WOULD use without touching
disk, and `socket_path_overflow` reports by how many bytes it misses — both in
`daemon/paths.py`, both reusing `_UNIX_SOCKET_PATH_LIMIT`, so a message built
from them cannot drift from the rule it is explaining.

This is remedy (2) of niggle N6 in Plan 00422. Remedy (1) shipped and made
worktree CREATION fail loudly; this covers the checkout that already exists, or
any other route into the same state.

## Goals

- When the natural socket path overflows, the skip reason says so, with the
  measured length and the cap, instead of blaming a stopped daemon.
- When it does not overflow, the reason is unchanged — the existing advice is
  right in the ordinary case.

## Non-Goals

- **Remedy (3), shortening the default socket filename, is deliberately NOT
  done here.** See the Decision below.
- No change to `get_socket_path`'s `/tmp` fallback. Falling back is correct;
  only the explanation of its consequences was missing.
- Nothing about N6's fault 2 (the playbook-harness stall), which still needs
  diagnosis before any remedy.

## Decision: remedy (3) is not worth its cost now

The ledger listed "shorten the default socket filename" as the cheapest remedy,
and it was — when nothing caught the overflow. Remedy (1) has since shipped:
`setup_worktree.sh` measures the prospective path and refuses before creating
anything, naming the length, the cap and how many characters to cut.

Renaming `daemon-{hostname}.sock` buys about five bytes and changes a runtime
path for every installation, in a project where a stale socket from a previous
container is already a thing that happens. Five bytes against a measured margin
of four characters is not nothing — but it narrows a class that is now
announced loudly at the moment it would bite, and the rename's blast radius is
every client that resolves the path.

Recorded rather than done, with the reasoning, so the option stays open if the
margin ever bites again.

## Tasks

### Phase 1

- [x] ✅ **Task 1.1**: RED test — with no socket under `untracked/` and a
  project path long enough to overflow, the skip reason names the overflow
  and its measurement. Six tests over `socket_path_diagnosis`, covering the
  measurement, the cap, the "a restart will not help" statement, the
  characters-to-cut figure, and the installed layout overflowing sooner.
- [x] ✅ **Task 1.2**: Control — with a path that FITS, `socket_path_diagnosis`
  returns `None` and the reason is the plain "start the daemon" advice.
  `None` rather than an empty string, so the caller branches on presence
  rather than on truthiness of a message it did not build.
- [x] ✅ **Task 1.3**: Build the reason from `prospective_socket_path` /
  `socket_path_overflow`, shared by both fixtures via `_no_socket_reason()`
  rather than written twice. Verified end to end: this checkout fits, and the
  N6 branch name reports "109 bytes, 5 over the 104-byte AF_UNIX limit" —
  which is this ledger's own CORRECTED arithmetic, not the "one byte too long"
  the entry originally claimed.

### Phase 2: gate

- [x] ✅ **Task 2.1**: `llm_qa format`, then `llm_qa.py all` green with the
  daemon restarted after the last `src/` edit — 35/35, no failed gates. The
  index row and statistics went in BEFORE the run this time; on Plan 00442
  leaving them until after cost a gate on two correct `plan_qa` advisories.
- [x] ✅ **Task 2.2**: Record N6 remedy (2) and the remedy-(3) decision on Plan
  00422's `NIGGLES.md`; archive.

## Success Criteria

- [x] ✅ The two skip reasons differ, proved by a test of each.
- [x] ✅ The measurement comes from the daemon's own helpers, so it cannot
  drift from `_UNIX_SOCKET_PATH_LIMIT`.
- [x] ✅ `llm_qa.py all` green, 35/35.
- [x] ✅ This plan has no release-bound consequences: the changed text is a
  pytest skip reason in this repository's own acceptance suite, which no
  client project runs.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00443-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Delivered at `0d84fb7e` — `socket_path_diagnosis`, its six tests, and both
  fixtures sharing one reason builder.
- Archived in the following commit, with the README row and statistics.
