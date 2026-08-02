# Plan 00194: `bin/hooks-daemon` targets a daemon by CWD, not by its own anchor

**Status**: Complete
**Created**: 2026-08-01
**Owner**: joseph
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

`bin/hooks-daemon` resolves its **interpreter** from its own location (`$0`),
which is deliberate and documented. But the daemon it then **manages**
(socket / PID / log) is chosen by the CLI from the **current working
directory's** project root. The two anchors disagree.

Consequence: the same wrapper, invoked by absolute path from two different
directories, acts on two different daemons.

```bash
W=/workspace/untracked/dummy-client-repo/.claude/hooks-daemon/bin/hooks-daemon

cd /workspace && "$W" status
# Socket: /workspace/untracked/daemon-<host>.sock            ← the MAIN daemon

cd /workspace/untracked/dummy-client-repo && "$W" status
# Socket: …/dummy-client-repo/.claude/…/daemon-<host>.sock   ← the fixture's
```

Observed live during Plan 00193 Phase 4: running the **client fixture's**
wrapper from `/workspace` reported the **dogfood** daemon as "already running",
and `restart` then restarted the **dogfood** daemon (PID 1186876 → 1203331).
Nothing warned that the wrapper being invoked belonged to a different project.

## Goals

- A wrapper invoked by absolute path manages **its own** project's daemon, or
  refuses clearly when that is ambiguous — no silent cross-project action.
- Whatever the resolution rule ends up being, it is **one** rule, stated once,
  and true of both the interpreter and the daemon.
- Existing worktree and self-install workflows keep working.

## Non-Goals

- Changing `--project-root` / env-var precedence semantics.
- Re-litigating the `$0` interpreter anchoring — that part is correct.

## Context & Background

The documentation half of this defect is already fixed (Plan 00193): the
wrapper's DESIGN NOTES asserted "It anchors to its OWN location (not the
caller's CWD)", which a reader reasonably takes to mean the whole wrapper. It
now states explicitly that the anchoring covers the interpreter ONLY, with a
worked cross-project example. **This plan is about the behaviour.**

`CLAUDE/development/CLIENT-MODE-TESTING.md` already documents the CWD trap for
the fixture, so the behaviour is known — but it is recorded as a testing gotcha
rather than recognised as a footgun in the product's single recommended entry
point.

### Why this is more than cosmetic

- The blast radius is *restart/stop on the wrong project's daemon*, which is
  silent and looks like success.
- It is most likely to fire exactly where the wrapper is most needed: an agent
  or script driving a daemon by absolute path from elsewhere.
- It contradicts guidance Plan 00193 just wrote into `Worktree.md` ("use the
  worktree's own wrapper"), which only holds if the wrapper's identity actually
  determines the target.

### Observed in the wild (Plan 00193 Task 6.7, commit 56f5e732)

This is no longer hypothetical. `scripts/dummy-client-repo.sh` invoked
`daemon.cli stop` with neither a `cd` nor `--project-root`. Run from
`/workspace`, the stop resolved the DOGFOOD project, found no dummy PID file,
printed **"Daemon not running"**, and exited **0** — after which teardown
deleted the fixture tree around a live daemon, orphaning it while reporting a
clean teardown.

Two properties of that failure are the ones this plan must design against:

1. **It is indistinguishable from success.** A stop targeting the wrong project
   legitimately finds no PID file, so it reports the truthful-but-useless
   "Daemon not running" and exits 0. Callers cannot tell "nothing to stop" from
   "stopped the wrong thing".
2. **It was harmless only by luck.** No `daemon-dummy-client-repo.pid` happened
   to exist under `/workspace`. With a host and container sharing a bind-mounted
   `untracked/` — a configuration `CLAUDE.md` explicitly supports — the same
   call stops a DIFFERENT project's daemon and still reports success.

Fixed locally in that script with an explicit `--project-root` plus a
post-condition that verifies the process is actually gone. That is a workaround
at one call site; this plan is the systemic fix.

## Tasks

### Phase 1: Establish the intended contract

- [x] ✅ **Task 1.1**: Enumerate every caller shape — self-install root wrapper,
  client `.claude/hooks-daemon/bin/`, worktree wrapper, skill `daemon-cli.sh`,
  hook forwarders — and record which daemon each SHOULD target.
- [x] ✅ **Task 1.2**: Decide the rule. Candidate: derive project root from the
  wrapper's own location (client mode `$DAEMON_DIR/../..`, self-install
  `$DAEMON_DIR`) and pass it as `--project-root` unless the caller supplied one.
  Verify against every shape from 1.1 before adopting it.
- [x] ✅ **Task 1.3**: Confirm precedence stays: explicit `--project-root` >
  env overrides > derived anchor.

### Phase 2: Implement (TDD)

- [x] ✅ **Task 2.1**: Failing tests first — same wrapper, several CWDs, asserting
  it targets its own project every time.
- [x] ✅ **Task 2.2**: Implement in BOTH `bin/hooks-daemon` and
  `src/claude_code_hooks_daemon/install/templates/hooks-daemon`; they must stay
  byte-identical (`tests/unit/install/test_bin_wrapper.py` enforces this).
- [x] ✅ **Task 2.3**: Regression-test the worktree case explicitly — a worktree's
  own wrapper manages the worktree's daemon, and `/workspace`'s manages
  `/workspace`'s, regardless of CWD.

### Phase 3: Verify in client mode

- [x] ✅ **Task 3.1**: Reproduce the original cross-project restart in the fixture
  and prove it no longer happens.
- [x] ✅ **Task 3.2**: Full QA green; both dogfood and fixture daemons RUNNING and
  independently controllable.
- [x] ✅ **Task 3.3**: Reconcile `CLIENT-MODE-TESTING.md` — if the behaviour
  changes, its CWD warning must be updated rather than left contradicting.

## Dependencies

- Related: Plan 00193 — fixed the documentation half and found this.
- Related: Plan 00192 — introduced the wrapper.

## Technical Decisions

### Decision 1: Split the documentation fix from the behaviour fix

**Context**: Both halves were found together during Plan 00193 Phase 4.

**Options Considered**:

1. Fix the behaviour immediately inside Plan 00193 — but that plan's scope is
   documentation accuracy, and changing project-root resolution in the single
   entry point every hook and script uses is not a tail-end change.
2. Fix the misleading comment now (it IS a documentation-accuracy defect, and
   leaving it asserts something untrue), and track the behaviour separately.

**Decision**: Option 2. The inaccurate DESIGN NOTE was corrected in Plan 00193;
the behaviour change is tracked here so the finding is not dropped.
**Date**: 2026-08-01

## Success Criteria

- [x] Same wrapper + different CWD ⇒ same target daemon, or an explicit refusal.
- [x] Worktree and self-install flows unchanged.
- [x] Wrapper documentation and `CLIENT-MODE-TESTING.md` agree with behaviour.
- [x] Full QA passes; daemon restarts RUNNING.

## Risks & Mitigations

| Risk                                                      | Impact | Probability | Mitigation                                                          |
| --------------------------------------------------------- | ------ | ----------- | ------------------------------------------------------------------- |
| Anchoring project root to `$0` breaks a legitimate caller | High   | Medium      | Task 1.1 enumerates every caller shape BEFORE the rule is chosen    |
| Hook forwarders depend on CWD resolution                  | High   | Medium      | Explicitly covered in 1.1 — forwarders are the highest-traffic case |
| Looks safe in self-install, breaks client mode            | High   | Medium      | Phase 3 verifies in the fixture, per CLIENT-MODE-TESTING.md         |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Activity log lives in JOURNAL/. -->

- Found during Plan 00193 Phase 4 client-fixture verification; documentation
  half fixed there, behaviour tracked here.
- Behaviour delivered in the Plan 00194 wrapper-anchoring commit: wrapper derives
  its own project root and passes `--project-root`; explicit caller flag still
  wins via argparse last-occurrence.
- **Follow-up correction (pre-v3.50.1 release review)**: the first cut kept a
  fallback — an unanchorable layout exec'd unanchored and let the CLI walk up
  from `$PWD`. That was labelled "fail-safe" and was not: the walk-up IS the
  defect this plan removes, so the fallback preserved it in the one case where
  nothing else could catch it. CWD is now never an input; an unanchorable
  layout exits 5 with a diagnostic. A wrong target that exits 0 is worse than
  a refusal.
- Phase 1 enumeration retired the plan's highest-rated risk: hook forwarders do
  NOT use this wrapper (they source `init.sh` and use the socket directly), so
  the highest-traffic path is untouched.
- Verified in the fixture: restarting the FIXTURE daemon while standing in
  `/workspace` left the dogfood daemon's PID unchanged (1629099), where the same
  command previously restarted it.
- Docs reconciled rather than left contradicting: `CLIENT-MODE-TESTING.md`,
  `Worktree.md`, and the wrapper's own DESIGN NOTE 1.
