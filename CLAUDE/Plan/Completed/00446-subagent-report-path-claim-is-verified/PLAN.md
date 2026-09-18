# Plan 00446: subagent report path claim is verified

**Status**: Complete
**Created**: 2026-09-18
**Owner**: dev
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Direct

## Overview

Ledger 00422 N15: a dedupe scout's final message ended `Report written to:`
followed by a path that was well-formed, matched the convention exactly, and
named a file that was never created. The verdict arrived inline and was
recoverable by hand, so it cost nothing that time. What it costs otherwise is a
PLAN.md citing evidence at a path that resolves to nothing.

No caller-stated value can catch this. Plan 00434's remedy for N13 — the
caller states the plan count so the agent's own enumeration can be checked
against something outside it — works, and is not in question. But N15 is the
report's own EXISTENCE claim being false, and the coordinator has nothing to
compare it against except the filesystem.

`subagent_report_size_blocker` (Plan 00307) establishes the shape. Its
reasoning transfers exactly: a coordinator cannot detect the failure by
inspecting what it received, because what it received looks right. So the
check belongs on the SUBAGENT side, at the moment it stops — the one point
where the claim and the filesystem are both in reach.

## Goals

- A subagent that claims in its final message to have WRITTEN a file is
  blocked from stopping when that file does not exist, and told to write it or
  drop the claim.
- The check is narrow enough to be trusted: a message that merely MENTIONS a
  path — one it read, one it is recommending — is never blocked.

## Non-Goals

- No verification that the content is any good, or that it matches what the
  dispatch asked for. This checks existence, which is the claim that was false.
- No change to `dispatch_declaration`. Reading the declared destination at
  SubagentStop is a larger question (the declaration is not carried on this
  surface), and N15's defect is detectable without it — the agent named the
  path itself.
- No change to `subagent_report_size_blocker`. Sibling handler, separate
  config key, separate failure.

## Tasks

### Phase 1: the claim detector

- [x] ✅ **Task 1.1**: RED first — `written_path_claims()`, observed failing on
  `ModuleNotFoundError` before the module existed. The control set
  (`TestAMentionIsNotAClaim`, 6 cases) passes unblocked: a path read, a path
  recommended, a bare path with no verb, a path inside a fence, a summary with
  no paths, an empty message. The verb set is past-tense/passive on purpose —
  "you should write X" is advice, and blocking advice would fire on most
  honest reports.
- [x] ✅ **Task 1.2**: The claim is resolved against the project root and
  stat'd. A path outside the root is never judged, and an unresolvable path
  fails open — an OS error is not evidence of a false claim.
  Root resolution follows `cron_subagent_stop_enforcer`'s resolver rather than
  `Path.cwd()`: a worktree dispatch would otherwise resolve a relative claim
  against the wrong checkout and report a written file as missing.

### Phase 2: the handler

- [x] ✅ **Task 2.1**: `SubagentReportPathVerifierHandler` on SubagentStop,
  with new `HandlerID` and `Priority` entries, registered in the config.
  **Non-terminal at priority 8, which is a correction to this plan's own
  premise**: the plan said "modelled on the size blocker: terminal". That
  would have been wrong twice over — the size blocker is terminal at 15 and
  matches nearly every stop, so anything after it is shadowed (which
  `test_stop_chain_terminal_shadowing.py` denies outright), and a terminal
  handler here would shadow the size blocker in turn. 8 is free on THIS event:
  the `release_blocker` holding 8 is a Stop handler. A report can be both
  unwritten and oversized, and the agent should hear about both in one stop.
- [x] ✅ **Task 2.2**: The deny names every missing path and gives two ways
  out, with the second stated as equal: stopping WITHOUT a path claim is
  legitimate when the report was genuinely short. It says outright not to
  create an empty file to satisfy the check — an invented report is worse than
  the claim it replaces, because it looks like evidence.
- [x] ✅ **Task 2.3**: `get_claude_md()` and `get_acceptance_tests()`, the
  latter rewritten after the invented signature I first used failed
  `type_check` — `AcceptanceTest` takes `title`/`expected_decision`/
  `expected_message_patterns`/`hook_input`, not `name`/`expected_outcome`.
  `handler_reference` now checks 138 handlers.

### Phase 3: gate

- [x] ✅ **Task 3.1**: `llm_qa.py all` green. The first full run came back 33/35,
  and both failures were one root cause that this plan **exposed but did not
  cause**: `handler_reference` flagged `subagent_cron_delete_blocker` (shipped
  by Plan 00423) as a PreToolUse blocking handler with no section in
  `docs/guides/HANDLER_REFERENCE.md`, and the `tests` gate's single failure was
  the integration test fronting that same check. Confirmed pre-existing against
  a worktree at `1b8e2692`, then fixed in its own commit `5f492887`. It
  surfaced now because the coverage rule reads the generated
  `.claude/HOOKS-DAEMON.md` inventory, which this plan regenerated — a stale
  inventory had been hiding the gap.
- [x] ✅ **Task 3.2**: N15's outcome recorded on Plan 00422, noting that it was
  closed by NEITHER remedy the entry listed, and why both were costed against
  the wrong surface. Regex worst case measured and journalled (0.12 s on a
  109 KB / 5000-claim message), because priority 8 means this handler sees the
  message before the size blocker trims it.

## Success Criteria

- [x] The control corpus of Task 1.1 was observed passing through unblocked —
  a guard that blocks everything would satisfy the positive tests alone.
- [x] A SubagentStop carrying N15's actual message shape, with no such file on
  disk, is denied and names the path.
- [x] The same message, with the file present, is allowed.
- [x] `llm_qa.py all` green.
- [x] Release-bound consequences recorded in the holding area:
  `CLAUDE/UPGRADES/UNRELEASED/release-notes/20-a-claimed-report-path-must-exist.md`
  (the callout — this ships a new user-visible handler, enabled by default) and
  an `added` entry for `handlers.subagent_stop.subagent_report_path_verifier`
  in `CLAUDE/UPGRADES/UNRELEASED/config-changes/v3.66.0.yaml`.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00446-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- `10b6d6f7` — the handler: claim detector, root resolution, non-terminal at
  priority 8, deny with two equal ways out.
- `38eb3eaf` — declared across the seven surfaces a new handler requires, plus
  the 0-9 priority-band rows and the regenerated `.claude/HOOKS-DAEMON.md`.
- `5f492887` — pre-existing doc drift this plan's regeneration exposed
  (`subagent_cron_delete_blocker`), fixed separately because it is not this
  plan's work.
