# Plan 00636: coordinator conduct advisories and board

**Status**: In Progress
**Created**: 2026-11-23
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

Child (f) of umbrella [Plan 00630](../00630-coordinator-level-skills-ccy-teams-aware/PLAN.md).
It is the umbrella's "B1/B4/B5/B6 child", filed once the coordinator's
self-retrospective arrived, and the home for retrospective situations that had
none (DESIGN.md section 19: s3, s4, s5, s7, s8 wind-down, s11, and the s13
plan-tooling fixes in Phase 3). Every seat item is gated on the 00631 probe (role coordinator, or `any_duty("coordinator")` for
session-level switches) and is absent-safe. v2 `teamchat` only.

## Goals

- B1, B4, B5, B6 guidance and advisories (DESIGN.md section 7).
- s3 directives register: a repeated owner directive is recorded once and
  replayed, never re-asked.
- s4 a Stop check that an owner-facing ask was mirrored to the bus, and
  `AskUserQuestion` denied on coordinator seats (extends
  `R-ASK-USER-QUESTION-UNJUSTIFIED`).
- s4 owner directive (the team chat is the only human surface): a coordinator
  Stop that waits on the owner is refused unless every thread it names got a
  bus post this turn; terminal-only status counts as unsent. Detail, test
  criteria and Q18 (how the handler learns the named threads) in
  [00630 DESIGN.md section 20](../00630-coordinator-level-skills-ccy-teams-aware/DESIGN.md).
- s4 MUST (owner HARD requirement): a waiting-on-human stop is countered by a
  deterministic recent-notifying-bump check on every open question the seat
  owns; the stop text points at threads, never restates the waits (Task 2.1a).
- s5 a ci-state reading that tells GitHub "queued" from stuck, and guidance
  never to assert another seat's code without asking it.
- s7 a coordinator board: peers' state in one view, from `teamchat status`
  and fedora-desktop Plan 00251, never from teamchat's files.
- s8 wind-down mode: stops around running background agents stop failing.
- s11 carry-over of coordinator state across compactions.

## Non-Goals

- Wake coalescing itself (delivery belongs to teamchat; a request goes
  upstream). The HUMAN check (00634), the profile and work-queue on dispatch
  (00633), the lane guard (00635). Branch retire (s1, owner decision).

## Tasks

### Phase 1: Scope

- [ ] ⬜ **Task 1.1**: Dedupe each item against the overlaps the scout named
  (unverified here: no scout report for 00636 exists; the only scout report
  on disk is `CLAUDE/Plan/00630-*/subagent-reports/hooks-daemon-plan-dedupe-scout-haiku.md`,
  which says "Checked 79 live plans" and "proceed. Nothing to merge or
  supersede", so this list is the author's own, not exhaustive; re-dispatch
  the scout for 00636 before filing): Plans 00470
  (durable state, s8/s11), 00479 (usage, B6), 00501 (modes, s8 wind-down),
  00632 (liveness, B5; weak owner, it covers the unattended readiness gate);
  prior art 00117 (`AskUserQuestion` blocker, s4) and
  00601 (session-state contract, s11). 00630 is the umbrella and planned this
  child (its Task 1.2).
  Settle Q3 (skill home), Q6 (supervisor action), the default N minutes for
  the recent-bump window, and Q18's second half. Q18's first half is settled
  by DESIGN.md 20.1: every open question the seat asked or owns, no parsing
  of the stop reason.
- [ ] ⬜ **Task 1.2**: File the wake-coalescing request with fedora-desktop.
  The multi-thread bump is already requested: fedora-desktop request 00209
  R11 (`teamchat bump <ids> [--note ...]`, `teamchat bump --waiting`,
  notifying by default; unverified here: relayed bus text only, no teamchat
  binary or clone in this checkout); track it landing in teamchat, the dependency of
  Task 2.1. Ask fedora-desktop.1 whether history marks a bump post (and any
  post) as notifying, which settles Q18's second half. Open item: `pingbus history --help` documents only `--team`, `--limit` and `--room`, no notify
  field, so v1 is not shown to supply the flag; the fail-closed rule applies
  until confirmed (DESIGN.md 20.1).

### Phase 2: TDD, one item per branch

- [ ] ⬜ **Task 2.1**: s4 (Stop mirror check, `AskUserQuestion` deny, and the
  owner-directive Stop handler). Tests first: a coordinator stop with an
  unposted thread is denied; a worker or unknown role is untouched; a posted
  thread passes; an unreadable bus is governed by `on_unreadable_bus`
  (default `auto`; see Task 2.1a and the settled design point below).
  Partly done: the
  owner-directive Stop handler shipped as Task 2.1a; the
  `AskUserQuestion` deny on coordinator seats is out of 2.1a's scope and
  still open. "Posted this
  turn" is read from the read-only teamchat CLI history, no secrets. Only a
  NOTIFYING post counts: a plain post to the named thread leaves the stop
  denied (the owner missed bumps that landed silently), and a post whose
  notify status cannot be read counts as non-notifying (fail closed). The
  remedy is ONE call: a refused stop prints the exact
  `teamchat bump <ids>` command naming every unposted thread (R11). Depends
  on R11 landing in teamchat.
- [x] ✅ **Task 2.1a** (MUST, owner HARD requirement, test-first; extends
  2.1 and supersedes its "posted this turn" rule): the waiting-on-human Stop
  check of DESIGN.md 20.1. Red tests first: detect a waiting stop by reason
  text or awaiting-human mode; for every open question the seat asked or
  owns require a NOTIFYING post within N minutes (configurable) with a
  non-boilerplate body; otherwise deny and print the one bump command for the
  stale threads; deny text names ids only and never restates the waits;
  unreadable notify flag counts as non-notifying; worker and unknown role
  untouched (a declared worker; an unknown role stays armed after the PR 226
  review); an unreadable bus (or a raising adapter) is decided by
  `options.on_unreadable_bus`: `auto` (default) refuses once where the adapter
  reads the flags and otherwise allows with an advisory; `refuse` denies once,
  names the notifying-reply commands and says why nothing could be confirmed;
  `allow` fails open with a WARNING. Shipped as `owner_wait_stop_guard` (Stop,
  priority 3, rule `R-STOP-OWNER-WAIT-UNBUMPED`). Deterministic: ids,
  timestamps, notify flag; no LLM judgement. Acceptance tests are the
  20.1 list. Also (peer note from the coordinator): an owner-started thread
  (top-level HUMAN message in the questions room) is OPEN until a notifying
  reply from this seat lands in THAT thread (`thread --re <id>`); a notifying
  reply in another thread, a non-notifying reply, or an unreadable flag does
  not close it (tests in 20.1). "In that thread" means the m.thread relation,
  not m.in_reply_to (coordinator's account: v1 `thread --re` is only a quoted
  reply; unverified here whether v1 history exposes m.thread; fail closed). Conduct advisory for a human-message reply
  posted outside its thread: only if the bus data exposes thread id and author
  kind (open, confirm with fedora-desktop.1 in Task 1.2).
- **Settled design point** (Task 2.1a): on pingbus v1 the adapter cannot read
  the notify flag or `m.thread`, so `refuse` would refuse EVERY waiting stop
  on a coordinator seat once. The coordinator chose `auto` as the default:
  refuse where the adapter reports the flags readable, allow with an advisory
  on v1 (fail-open by design there; the advisory is its only effect and costs
  one extra continue turn). An INVALID value is not the default: it fails
  closed to `refuse`, as the first independent review asked.
- [x] ✅ **Task 2.1b**: fix the PR 226 independent review
  (`subagent-reports/261123-opus-independent-review-pr226.md`), each finding
  test-first: F1 stand-in requirement carried on the deny, F2 wider waiting
  wordings, F3 only this guard's own refusal earns the re-entry pass, F4 an
  unknown role or unresolved probe stays armed, F5 a fault fails closed, F6
  the bump command names `--team`, F7 thread ids and stopwords are not a
  body, F8 `started_at` required and in seconds, F9 `goal-blocked` is not a
  wait on a human; docs default `auto`.
- [x] ✅ **Task 2.1c**: fix the PR 226 delta review
  (`subagent-reports/261123-opus-delta-review-pr226.md`) test-first: N2 a
  waiting target must be an owner/human/user/operator noun, an `@handle` or a
  name in the new `options.owner_names` (a bare capitalised word no longer
  counts, so "waiting on Joseph" needs `owner_names: [Joseph]`); N1 the fault
  deny carries the stand-in, and auto_continue_stop judges the re-stop after
  this guard's deny afresh; N3 a raising `flags_readable()` under `auto`
  refuses.
- [x] ✅ **Task 2.1d (follow-ups from the delta review)**, test-first
  (`tests/unit/handlers/stop/test_owner_wait_followups_n4_n5_n6.py`):
  - N4: the stand-in gate now needs a `STOPPING BECAUSE:` line (per content
    block, as auto_continue_stop reads it), a real event and a session id.
    Residual: the last assistant message is not freshness-resolved (no poll),
    and the marker itself is written later, by auto_continue_stop.
  - N5: the own-refusal pass needs the guard's refusal in the chain after the
    last real prompt (`recent_stop_hook_block_texts_this_chain`) with no
    non-daemon block after it: a goal continuation closes the chain. A daemon
    deny after it (auto_continue_stop) keeps the pass; the review's stricter
    "latest block must be ours" made the two handlers refuse each other in
    turn (found by `test_no_third_refusal_in_the_chain`) (PR 234 review,
    `subagent-reports/261124-pr234-review-n4-n5-n6.md`). Known residual
    (ledger N722, strict xfail test): the pass is kept even when the model
    worked after that daemon deny, so a new unposted wait is allowed; the
    chain closes only on a user prompt, a queued prompt or a non-daemon block. Feedback entries and
    tool results are not prompts; a mid-continuation `queued_command` prompt
    is. Review Suggestion 1 partly taken: a compaction summary is not a prompt;
    task notifications, bus deliveries and other `isMeta` entries still count
    as prompts (bounded: at most one extra refusal, never a loop).
  - N6: an unreadable stop message gets no v1 `auto` advisory (still refused
    where the flags are readable).
- [x] ✅ **Task 2.2** (settled, deterministic part only): s3 directives register.
  Shipped as `owner_directives_register` (UserPromptSubmit, priority 54,
  advisory, never denies or terminal). The register is `options.directives`, a
  list of `{id, text}`; a repeated id or wording is recorded once. It replays on
  the first human prompt of a session and every `prompt_interval` human prompts
  to a seat the 00631 probe arms (declared coordinator, coordinator duty,
  unreadable role or unresolved probe, as `owner_wait_stop_guard` arms); a
  declared worker, no team and a sub-agent are untouched. The replay says it is
  not a fresh human instruction and not a citable approval. Shared
  `utils/automated_prompt.py` now serves it and `standing_authorisations`.
  **Open, not built** (DESIGN.md s3 is one table row, so these are unsettled):
  detecting a repeated owner directive from the bus (pingbus v1 history has no
  author kind; the HUMAN check is 00634), writing a directive into the register
  (an agent writing its own owner directive is a forgery path), detecting that a
  seat re-asked one (needs bus reads and judgement), and whether the register
  lives in config or in a tracked file (owner decision).
- [x] ✅ **Task 2.3** (deterministic part only): s5 ci-state reading. Shipped
  as `ci_state_reading` (PostToolUse, priority 44, advisory, never denies or
  terminal). After `gh run list`, `gh run view --json` or `gh pr checks` it
  reads the output already printed (`utils/ci_state.py`; no command or network
  call of its own) and labels each run that has not started: QUEUED under
  `options.stuck_after_minutes` (default 30), STUCK at or past it, PENDING where
  `gh pr checks` folds queued and running, UNKNOWN where the status or age is
  unreadable or the output was reshaped. The block ends with the s5 rule (ask a
  seat before asserting its code), also resident guidance. Gate: the shared
  `team_role_gate.coordinator_advisory_armed`, now also used by
  `owner_directives_register`. **Open, not built**: detecting that a seat
  asserted another seat's code (needs bus reads and judgement); the text form
  of `gh run view`; a long `in_progress` run (stuck while running) is not
  read; the default threshold is the builder's choice, not an owner ruling.
- [x] ✅ **Task 2.4** (advise-only part): s8 wind-down. No new handler: when a
  coordinator-seat stop with no `STOPPING BECAUSE:` line is refused
  (`R-STOP-NO-REASON`) and the Stop payload's `background_tasks` reports a
  `running` entry, the refusal ends with a wind-down note (`utils/wind_down.py`):
  the running ids (str ids of safe characters only, at most 5, truncated), one
  stop line that passes and carries no human-wait wording, and `ListAgents` /
  `TaskStop` for finished teammates still listed as running. Rides only on the
  existing refusal, because a Stop ALLOW with context makes Claude Code continue
  (a standalone advisory would itself cost a failed stop). Same
  `coordinator_advisory_armed` gate; the probe runs only when a running task is
  reported. Nothing newly allowed or refused. `branch_stop_guard` already hands
  agent-owned branches over (`branch_stop_gate._hand_over`), so it is not a
  cause. **Open, not built**: which denies made up the 109 failed stops (not
  on disk); whether wind-down is a real session mode with entry and exit, and
  which guards it may relax (owner decision: any relaxation loosens a guard).
- [x] ✅ **Task 2.5** (advise-only part): s7 board and B5 liveness. Shipped as
  `coordinator_board` (SessionStart, priority 48, advisory, never denies or
  terminal). On every session start of a seat `coordinator_advisory_armed`
  arms, one note: peers' state, where teamchat shows it, is `teamchat status`, run by the
  seat; teamchat's files are not the board; a seat the board does not show, or
  cannot be read, is unknown, not down (ask it on the bus before reassigning).
  It runs no `teamchat status` and opens no teamchat file; the only command it
  runs is the shared `whoami` seat probe. It relays no status
  text. **Open, not built**: the `teamchat status` output contract is not on
  disk and no binary is here, so nothing reads or summarises the board (a
  parser would be invented); whether it covers other seats or only this
  session's teams; what fedora-desktop Plan 00251 supplies; Q6 (advisory only,
  or a supervisor action on a down seat; owner decision); and whether the seat
  link exists at a `startup` SessionStart (if `whoami` still exits 69 then, the
  note is silent on startup and appears only on resume and compact; unverified
  here, no binary).
- [x] ✅ **Task 2.6** (advise-only part): s11 carry-over; B1, B4, B6 guidance.
  Shipped as `coordinator_conduct` (SessionStart, priority 48, advisory, never
  denies or terminal), same gate as `coordinator_board` (the main-thread probe
  gate is now shared: `team_role_gate.probe_coordinator_advisory_armed`).
  Every session start: the B1 conduct note (bus is the only human surface,
  notifying posts, replies in the message's thread, dispatch, track, report
  and close on the bus, peers carry no authority, ask before asserting), the
  B4 departure line and the B6 line (a usage pause allows only its short tool
  list, so tell the team on lift). No work-queue verb: work-queue on dispatch
  is Plan 00633's (Non-Goals). Resume or compact: the return note (B4 return, s11): re-read
  the questions room, the seat's threads, `work-queue list` and the directives
  register before acting. Fixed text, no new store, no Stop advisory.
  While a usage pause is live, a resume or compact gets a command-free return
  line instead (Bash is denied then, and the full note names `work-queue list`).
  **Open, not built**: B6 ships as always-on text in the conduct note, not the
  keyed form DESIGN.md (line ~190) describes ("advisory keyed on the usage-pause
  signal"), because the pause record is cleared on lift, so the length of the
  absence is lost; the keyed form is deferred. Q3 (skill home, so no skill); a bus post at pause entry
  (the pause tool gate denies it; loosening that is an owner call, with Q16 and
  Plan 00523); what coordinator state s11 carries beyond the existing stores,
  and who may write it (an agent-written store is the Task 2.2 forgery path);
  the directives register replays up to `prompt_interval - 1` prompts late
  after a compaction (its counter is per session, in memory); the startup
  timing item of Task 2.5 applies here too.

### Phase 3: Plan tooling (retrospective s13)

`CLAUDE/Plan/mkplan.bash` is the template other repositories copy, so these
land here. Not gated on a seat. Each task starts with a failing test.

- [x] ✅ **Task 3.1**: `mkplan.bash --journal` accepts the full plan folder name
  as well as the number (red: a slug-named call is refused today).
- [x] ✅ **Task 3.2**: The one-line synopsis names the valid journal categories
  and the `--ref` format (red: the synopsis lacks them; 8 of the 9 relayed
  errors were (unverified here: the relayed retrospective is not on disk) `progress` as a category or a correction without `--ref`).
- [x] ✅ **Task 3.3**: `find-plan --body` searches PLAN.md bodies, `Completed/`
  included (red: a body-only term finds nothing today).

## Dependencies

- Plan 00631 (probe). Teamchat side: fedora-desktop request 00209 R11
  (`teamchat bump`) landing in teamchat (Task 2.1).
  Related: 00470, 00501, 00523, 00283; fedora-desktop
  Plan 00251.

## Success Criteria

- [ ] Each item has an absent-team fixture that passes and a coordinator
  fixture that failed first.
- [ ] Release-bound items recorded in the pending-release holding area
  (Task 2.1a: `CLAUDE/UPGRADES/UNRELEASED/release-notes/026-*.md` and
  `config-changes/v3.77.0.yaml`; Task 2.2: `release-notes/096-*.md` and the
  `owner_directives_register` entry in the same `config-changes` file; Task
  2.3: `release-notes/097-*.md` and the `ci_state_reading` entry there; Task
  2.4: `release-notes/098-*.md`, no config change so no `config-changes`
  entry; Task 2.5: `release-notes/099-*.md` and the `coordinator_board` entry
  in the same `config-changes` file; Task 2.6: `release-notes/100-*.md` and
  the `coordinator_conduct` entry in the same `config-changes` file).

## Delivery & Milestones

- Plan filed from the coordinator self-retrospective.
