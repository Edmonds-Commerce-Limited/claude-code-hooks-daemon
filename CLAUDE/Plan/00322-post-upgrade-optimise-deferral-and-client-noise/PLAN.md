# Plan 00322: post upgrade optimise deferral and client noise

**Status**: In Progress
**Created**: 2026-09-02
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Direct

## Overview

Owner field report from a real client upgrade (≤v3.58.x → v3.60.0): the
upgrading agent finished, then filed the config-optimisation review under
"Left for you to decide" as "Run `/optimise` at some point to silence the
new config-optimisation reminder at session start". Plan 00308 made that
review MANDATORY, so the outcome contradicts the design.

The cause is our own wording, not agent disobedience. `scripts/upgrade.sh`
checks the target version out FIRST and then delegates to the NEW
`upgrade_version.sh`, so the v3.60.0 banner really did print — and the
banner says "MANDATORY NEXT STEP: run the config-optimisation review **in
your next Claude Code session**", immediately after a block telling the
agent to exit its session. A mandatory step scheduled for a session that
does not exist yet is, to the agent finishing the upgrade, an optional
follow-up note. The `config_optimisation_reminder` safety net then fires
next session with equally deferrable phrasing plus a "silence this
reminder" escape hatch, and gets deferred again.

The same field report surfaced a second session-start advisory the client
could not act on: `contract_staleness` told the project its vendored hooks
contract was stale against Claude Code v2.1.258 and pointed at
`docs/guides/HOOK-CONTRACT-REFRESH.md`. That procedure edits
`contracts/claude-code-hooks/*.json` and re-runs this repo's
`scripts/qa/check_hook_contract.py` — upstream-maintainer work. In a client
install those files live under `.claude/hooks-daemon/`, which the upgrade
contract forbids editing and overwrites on the next upgrade, so the advisory
asks a client for a change that is both out of scope and self-destructing.

## Goals

- The post-upgrade banner directs the agent to run `/optimise` in the
  CURRENT session, before it reports the upgrade done — no wording that
  schedules it for a later session.
- The banner and the "restart Claude Code" instruction are ordered so the
  agent does not read "exit your session" before the step it must still do.
- `contract_staleness` gives a client install an action a client can
  actually take (upgrade the daemon, else report upstream) and never points
  a client at the maintainer refresh procedure or at editing
  `.claude/hooks-daemon/`.
- Every wording contract above is covered by a test, so the next edit that
  reintroduces deferral phrasing fails CI.

## Non-Goals

- Auto-running `/optimise` without an agent in the loop, or auto-enabling
  handlers (unchanged Plan 00308 contract: recommend, apply on explicit
  confirmation).
- Changing what `/optimise` analyses.
- Suppressing `contract_staleness` entirely in client installs — a stale
  contract is a real risk the client should know about; only the
  REMEDIATION is maintainer-only.

## Tasks

### Phase 1: Post-upgrade banner stops deferring

- [x] ✅ **Task 1.1**: Add a banner-wording contract test under
  `tests/unit/scripts/` asserting the shipped text: no next-session
  deferral phrasing, an explicit current-session imperative, the
  `--skip-config-optimisation` branch intact, and the "restart Claude Code"
  block positioned AFTER the banner. RED first.
- [x] ✅ **Task 1.2**: Reword and reorder the tail of
  `scripts/upgrade_version.sh` until Task 1.1 is GREEN.
- [x] ✅ **Task 1.3**: Align the two prose surfaces that repeat the same
  instruction — `skills/hooks-daemon/upgrade.md` step 8 and
  `CLAUDE/LLM-UPDATE.md`'s mandatory step (which also asserts, wrongly,
  that "New handlers ship DISABLED by default" — four handlers in the
  v3.59.0/v3.60.0 range ship enabled).
- [x] ✅ **Task 1.4**: Same treatment for the safety net that was deferred
  the same way — `config_optimisation_reminder` now binds the review to the
  current session, states it is the deferred mandatory step rather than a
  to-do, and demotes the `record-config-optimisation-run` silence command to
  a qualified last resort. Test-locked.

### Phase 2: `contract_staleness` becomes install-mode aware

- [x] ✅ **Task 2.1**: Extend
  `tests/unit/handlers/session_start/test_contract_staleness.py` with the
  client-install case: the advisory names the daemon-upgrade / report-
  upstream action, does NOT cite the refresh procedure, and warns against
  editing `.claude/hooks-daemon/`. Self-install keeps today's message.
  RED first.
- [x] ✅ **Task 2.2**: Implement the branch in
  `src/claude_code_hooks_daemon/handlers/session_start/contract_staleness.py`,
  resolving install mode from `ProjectContext.self_install_mode()` with a
  fail-safe fallback (an uninitialised context must not crash session
  start).

### Phase 3: Ship phases 1-2

- [ ] ⬜ **Task 3.1**: Full QA, daemon restart + verification, CHANGELOG
  entry, commit and push.

### Phase 4: `optimise` stops squatting a generic top-level name

Owner call, raised while phases 1-2 were in flight: `optimise` is far too
generic a slash command for a skill this daemon deploys into every client —
it collides with any project or plugin skill of the same name, and the
project's own skill would lose or win the name unpredictably. It belongs
under the daemon's namespace as a `hooks-daemon` subcommand, like `upgrade`,
`health` and `bug-report`. Plan 00308 chose the standalone name; this
supersedes that choice.

- [ ] ⬜ **Task 4.1**: Move the skill body to
  `skills/hooks-daemon/optimise.md` (+ its `invoke.sh`), add the SKILL.md
  command-list entry, and stop deploying the standalone `skills/optimise/`.
- [ ] ⬜ **Task 4.2**: Migration for installs that already have
  `.claude/skills/optimise/` deployed — the installer must remove the
  orphan, and the change needs a truth-changes entry so client docs
  asserting `/optimise` are reconciled on upgrade.
- [ ] ⬜ **Task 4.3**: Re-point every reference: the upgrade banner,
  `config_optimisation_reminder`, `skills/hooks-daemon/upgrade.md`,
  `LLM-INSTALL.md`, `LLM-UPDATE.md`, the state module docstrings and the
  `record-config-optimisation-run` CLI help.

## Success Criteria

- [ ] No shipped upgrade surface tells the agent to run the
  config-optimisation review in a later session.
- [ ] A client-install `contract_staleness` advisory is actionable by the
  client without editing daemon-owned paths.
- [ ] Both wordings are locked by tests that fail if the phrasing regresses.
- [ ] QA green; daemon restarted and verified before commit.
- [ ] The config-optimisation review is invoked through the `hooks-daemon`
  skill namespace, and no install is left holding an orphaned standalone
  `optimise` skill.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00322-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- <!-- milestone or delivery commit hash -->
