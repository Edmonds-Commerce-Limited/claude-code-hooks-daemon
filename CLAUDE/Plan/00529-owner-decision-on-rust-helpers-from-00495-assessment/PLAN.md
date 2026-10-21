# Plan 00529: owner decision on rust helpers from 00495 assessment

**Status**: In Progress
**Created**: 2026-10-16
**Owner**: dev
**Priority**: Medium
**Themes**: performance
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Plan 00495 Task 3.2 asked whether particular heavy paths justify a Rust helper (owner ruling A3). It answered from the
measured numbers in [RUST-HELPERS-ASSESSMENT.md](../Completed/00495-performance-improvement-programme/RUST-HELPERS-ASSESSMENT.md):
no path passes the cost test, one path is heavy for a Python reason, and the one helper that was justified (the transport
relay) already exists, opt-in. The choice is the owner's, so this plan holds it until they make it, and carries the work
that follows whichever way they decide.

The path that is over the performance budget is the secret-file guard's scan of Write and Edit content: about 9 ms per KB,
so a 115 KB Write spends 1.2 s in that one handler, and a 1.15 MB Write 9.3 s. The assessment recommends a Python fix, not
a helper. That fix is a Python change tracked as ledger N465 and fixed separately, so it is not in this plan.

## Goals

- The owner decides, from the assessment, on its two recommendations that are theirs: no new native helper, and the relay
  staying opt-in.

## Non-Goals

- A full Rust rewrite of the daemon or its handlers.
- Compiling any policy (Plan 00154 Rule 1).
- A new native helper commissioned without a measured case.

## Tasks

### Phase 1: Decide

- [x] ✅ **Task 1**: The owner decided, in session messages while #131 was being worked:

  - **(b) The relay is the new default, starting with the status line.** In the owner's words: "wondering if we can
    have rust for statusline by default ... or maybe we make rust the new default and see how it goes". The project
    has no consumers but the owner, so there is no support cost to weigh.
  - **(a) Rust is welcome where it pays.** The owner wants it suggested "for other stuff as well". No specific helper
    is commissioned yet. Each candidate is still measured against the assessment's cost test.
  - **Performance is now a priority.** In the owner's words: "the paradigm is definitely shifting to having lots of
    claude code sessions running, and that means hooks daemon/status line load is increasingly important".
  - **A standing principle, for this work and the repository:** "this repo should not have silent fallbacks - that is
    error hiding - we need this repo to have LOUD AND CLEAR FAIL FAST". A configured transport that is not in use (ledger
    N523) is a loud failure, not a silent fall back to bash.

### Phase 2: Act on the decision

- [ ] 🔄 **Task 2**: The relay becomes default-on.
  - [x] Install and upgrade put the binary in place: build with `rustc` and the musl target when present, otherwise the
    digest-verified release asset. Where neither works, the failure is loud and names the fix. Merged `59320d842`:
    - `relay_source: auto`;
    - new configs enable the relay;
    - an upgrade picks the default up only for a config with no `transport` block (a coordinator ruling, overturnable);
    - a provisioning failure completes the install with a banner repeated before exit, naming the path and the fix.
    - Report: [subagent-reports/261021-task-2b-install-provisioning-opus.md](subagent-reports/261021-task-2b-install-provisioning-opus.md).
  - [x] The status line uses the relay (Plan 00542, merged `901e59a7a`). A missing binary prints a red line naming
    `bin/hooks-daemon transport on`.
  - [x] A configured relay that is missing or not executable is reported loudly: `transport on` reports a provisioned
    binary (N525), and `status` and the new SessionStart `relay_binary_checker` name the path and the fix (N523).
    Merged `376612d38`.
  - [ ] **Open owner question**: what a relay-eligible SAFETY forwarder (PreToolUse and similar) does when the binary is
    missing. Today its guard falls through to the bash path, which still enforces every rule but is slower and silent
    at the moment of the call. Denying every tool call would also deny the commands that rebuild the relay. The
    coordinator's recommendation, held until the owner rules: repair automatically at session start and upgrade; if
    that fails, deny every tool call except the repair command, naming it; never a silent bash path. The SessionStart
    and `status` warnings above already make the missing binary loud.
- [x] ✅ **Task 3**: Measure the default-on relay against bash on the hot hooks, under many concurrent sessions, and list
  further Rust candidates with their numbers for the owner. Report:
  [subagent-reports/261021-task-3-measurements-opus.md](subagent-reports/261021-task-3-measurements-opus.md).
  - Client side, per call: 4.3-5.6 ms CPU through the relay against 79-82 ms through bash. At 16 sessions, 0.16 cores
    against 2.73.
  - The daemon is now the cost: PreToolUse Bash takes 49.5 ms CPU per call, which caps one daemon at about 30
    sessions (extrapolated from the 16-session run, not measured).
  - Ranked candidates, none of them Rust:
    1. `prevent-destructive-git` parses the command once instead of 18 times (measured 36% off PreToolUse Bash, for
       commands that mention git).
    2. One shared parse across the Bash guards.
    3. Move `SCRIPT_DIR` after the relay check in the forwarder (4.3 to 2.2 ms client CPU).
  - No further Rust helper passes the Plan 00495 cost test yet.

## Success Criteria

- [x] The owner's decision on (a) and (b) is recorded in this plan.
- [ ] The relay is default-on, and a configured-but-missing relay fails loudly with the fix named.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00529-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Filed by Plan 00495 Task 3.2.
