# Plan 00493: upgrade silently disables opt-in handlers

**Status**: In Progress
**Created**: 2026-10-05
**Owner**: dev
**Priority**: High
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A client agent reported after upgrading from v3.67.0 to v3.68.0: "The upgrade
had silently switched off 11 opt-in handlers this project relied on". The
owner sees the same complaint across client projects. That line is the
agent's own conclusion, not daemon output. It is correct.

**Root cause (confirmed and reproduced).** Plan 00483 N55, an
owner-delegated ruling, was implemented in `02c702ea2` and merged in
`ae62d27d1`. It changed how a handler with NO block under `handlers.<event>`
is resolved:

- At v3.67.0, `registry.py:237` treated an absent block as enabled for every
  handler.
- At v3.68.0, `registry.py:248-249` returns "off by default and not
  configured" for an opt-in (`default_enabled = False`) handler.

Every client config that omits an opt-in handler therefore loses it. The
change is intended, but nothing tells the project WHICH handlers it lost:

- The 16 config-changes entries are documentation-only.
  `config_migrations.py:659` skips an entry with no `recommended_value`, so
  the upgrade reports nothing for them.
- The truth change prints a generic list of 16, but there are 17. It omits
  `plan_fact_check_feed`.
- The skip is logged at DEBUG.
- The upgrade's `config_diff_summary` always says "no config changes".
  `upgrade.sh:958` reads `hooks-daemon.yaml.backup`, which nothing writes;
  `config_preserve.sh:75-77` writes `.backup-<timestamp>`.

HEAD (main) is unchanged in all four respects.

**Blast radius.** Every `init minimal` config loses 16 handlers. A full
config generated before v3.67.0 loses 1-14; one from v3.40-v3.54 loses
exactly 11. Hand-written or partial configs are affected too.

No default-on handler changed. A block that is present, even a bare key or
an options-only block, stays enabled.

Evidence, the reproduction and per-version tables are in
[subagent-reports/261005-optin-upgrade-investigation-opus.md](subagent-reports/261005-optin-upgrade-investigation-opus.md).

Scope, by owner direction: 80/20, made right going forwards. The remedy for
already-upgraded clients is a short note, not a project.

## Goals

- An upgrade that changes a project's effective enabled-handler set says so
  loudly, by name, every time.
- Git history shows plainly when a project's daemon version changed, and
  from what to what.

## Non-Goals

- Reverting N55. It is an owner ruling, and the new semantics are correct.
- Auto-enabling handlers for clients (an owner question, below).
- Retroactive tooling for clients that have already upgraded.

## Tasks

### Phase 1: make the change visible (TDD)

- [x] ✅ **Task 1.1: report the effective-set change on upgrade.**
  - Compute the set the client's ACTUAL config registers under the old
    version's rules and under the new version's rules. Use one shared
    helper built on `handler_is_enabled` and the class `default_enabled`.
    The old side may need a recorded "absent means enabled" rule for
    versions before v3.68.0.
  - `upgrade.sh` prints a prominent block listing every handler that STOPS
    or STARTS running, each with its key and the snippet to keep it.
  - The upgrade metadata carries the same list.
  - Fix the `config_diff_summary` backup path (`upgrade.sh:958` against
    `config_preserve.sh:75-77`), so the summary can never say "no config
    changes" when the file or the effective set changed.
  - Correct "sixteen" to seventeen (`plan_fact_check_feed`) in the v3.68.0
    truth change, release note 216 and config-changes. Better: generate the
    list from the classes.
- [x] ✅ **Task 1.2: the upgrade summary names the version change.** The daemon version is already tracked; this is
  only the from → to line.
  - What exists today: v3.68.0 (Plan 00477) writes `daemon.expected_version`
    into the tracked `.claude/hooks-daemon.yaml` on install and upgrade
    (`install/expected_version.py`; `upgrade_version.sh:1046,1636`). The
    tracked `.claude/HOOKS-DAEMON.md` header also names the version, and
    `init.sh` `_resolve_expected_version` reads both. The config's
    `version: "2.0"` is the schema version, not the daemon version. So the
    owner's belief holds from v3.68.0 on: `git log -p -S expected_version .claude/hooks-daemon.yaml` shows each change.
  - Remaining gap: make the upgrade summary name `from → to`, and point the
    committing agent at a commit message that says
    `hooks daemon vX → vY` together with the Task 1.1 handler delta.
- [x] ✅ **Task 1.3: regression test.**
  - Fixtures: an `init minimal` config, a v3.50.0 `init full` config and a
    v3.67.0 `init full` config.
  - Any rule change that alters the effective set for a fixture must appear
    in the Task 1.1 report.
  - Pin that the report is non-empty for the first two fixtures and empty
    for the third.
  - Pin that the "no config changes" summary is impossible while the set
    differs.

### Phase 2: client note

- [x] ✅ **Task 2.1: remedy note for already-upgraded clients.**
  - Add a short release note or `LLM-UPDATE.md` paragraph:
    - run `.claude/hooks-daemon/bin/hooks-daemon optimise-checklist`;
    - for each `[default off]` handler the project wants, add
      `handlers.<event>.<key>: {enabled: true}`;
    - restart.
  - Recommend naming only the wanted handlers. Several are noisy, and four
    deny tool calls.

## Later / owner questions

- **Owner question:** should the upgrade AUTO-write `enabled: true` for
  handlers that ran before? That preserves behaviour, but keeps noisy or
  deny-capable opt-ins running in clients that never chose them, which is
  what N55 removed. Alternative: a one-command opt-in that the report
  offers.
- Later: scan the git history of `.claude/hooks-daemon.yaml` at upgrade time
  for other likely losses, such as removed or renamed keys still set.
- Later: the Step 10 config merge (`preserve_config_for_upgrade`) writes
  `enabled: false` for every absent opt-in block when it runs. Confirm when
  it runs on a client upgrade, and route it through the Task 1.1 report.

## Success Criteria

- [x] An upgrade from v3.67.0 on an `init minimal` fixture prints every
  handler that stops running, by name.
- [x] `config_diff_summary` reflects real config changes.
- [x] The Task 1.3 regression test is green, and was red before Task 1.1.
- [x] The client remedy note is published.

## Delivery & Milestones

- Investigation: [subagent-reports/261005-optin-upgrade-investigation-opus.md](subagent-reports/261005-optin-upgrade-investigation-opus.md)
