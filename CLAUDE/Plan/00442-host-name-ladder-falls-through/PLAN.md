# Plan 00442: host name ladder falls through

**Status**: In Progress
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Low
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

`utils/host_identity.py` opens by describing its resolution order: "Resolution
is a ladder, first hit wins", with four rungs — an explicit environment
hand-off, `socket.gethostname()` where it means something, an `/etc/hosts`
self-alias, and nothing.

`resolve_host_name` does not do that. Inside the rung-2 branch, when the
runtime is one where `gethostname()` is meaningful but the value cleans to
nothing, it returns `None` outright — skipping rung 3 and landing on rung 4.
The docstring says a rung that does not hit falls through; the code says a rung
that APPLIES is final whether it hits or not.

The fix is to make the code match the documented ladder, and the module's own
reasoning is why that is the right direction rather than editing the prose.
Rung 2's condition is about the RUNTIME — "is `gethostname` meaningful here" —
not about the value it returned, so a rung that produced nothing usable is a
rung that did not hit. And rung 3 is already described as "a hint, marked as
one, ranked below every route that cannot be wrong": it is designed to be the
last resort, which is exactly the position it would occupy here. On a host
where `gethostname()` somehow yields nothing, a `127.0.1.1 <hostname>` line in
`/etc/hosts` genuinely names that host — returning nothing instead is losing an
answer the module already knows how to label.

This is niggle N5 row (e) of the ledger in Plan 00422, and its last open row.

## Goals

- `resolve_host_name` falls through from rung 2 to rung 3, as documented.
- The provenance of the fallen-through answer is still `ETC_HOSTS_HINT`, so
  nothing is dressed up as more reliable than it is.

## Non-Goals

- No change to rung ordering, to `_HOSTNAME_MEANINGFUL_RUNTIMES`, or to what
  counts as a clean host name.
- No config-file override. The module argues at length against one — a machine
  name in a tracked, routinely-public YAML is a leak discoverable only by
  searching history that is never rewritten — and that argument is untouched.

## Tasks

### Phase 1

- [x] ✅ **Task 1.1**: RED test — in a hostname-meaningful runtime whose
  `gethostname()` returns an unusable value, an `/etc/hosts` self-alias is
  still resolved, with `HostNameSource.ETC_HOSTS_HINT`.
- [x] ✅ **Task 1.2**: Controls — a usable `gethostname()` still wins rung 2
  and reports `LOCAL`; with neither, the result is still `None`. Both green
  before and after.
- [x] ✅ **Task 1.3**: Replace the early `return None` with a fall-through.
  The module docstring needed no edit: "a ladder, first hit wins" is now
  simply true of the code.

**Two things the suite already knew.** `test_a_refused_rung_does_not_stop_the_ladder`
asserts exactly this principle — but forces a `podman` runtime, so rung 2 never
runs and its own case went untested. And `_silent_hosts`' docstring states it
outright: "Refusing a hostile value never meant NOTHING resolves — only that
the refused rung contributes nothing." The code disagreed with its own tests'
stated reasoning, not just with its docstring.

**One existing test had to be corrected**, and it is the best evidence the
change is right: `test_a_hostile_local_hostname_is_refused` asserted `None`
without pinning `hosts_path`, which is precisely the hazard `_silent_hosts`
was written to prevent. It passed only because rung 2 short-circuited before
the last rung could read the real `/etc/hosts`. It now pins the hosts file, so
it asserts what it means — that rung 2 contributes nothing — rather than
depending on the host distribution.

### Phase 2: gate

- [ ] ⬜ **Task 2.1**: `llm_qa format`, then `llm_qa.py all` green with the
  daemon restarted after the last `src/` edit.
- [ ] ⬜ **Task 2.2**: Record row (e) on Plan 00422's `NIGGLES.md`; archive.
  No release note: the only consumer is a status-line segment, and the
  change is "shows an inferred name where it previously showed nothing".

## Success Criteria

- [ ] The documented ladder and `resolve_host_name` agree, checked by a test
  rather than by reading them side by side.
- [ ] The two controls pass unchanged.
- [ ] `llm_qa.py all` green.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00442-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
