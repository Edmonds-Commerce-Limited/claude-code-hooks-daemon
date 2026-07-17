# Plan 00176: settings.json merge — preserve client customizations on upgrade

**Status**: Not Started
**Created**: 2026-07-17
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The installer and upgrader deploy the daemon's own `.claude/settings.json` into
client projects by **verbatim copy**, never a merge. On a fresh install the
client's existing file is backed up then overwritten
(`scripts/install_version.sh:357-363`); on **every upgrade** it is overwritten
again (`scripts/upgrade_version.sh:663-665`, Step 9 "Redeploying settings.json").
The config-preservation machinery that survives client customizations
(`scripts/install/config_preserve.sh` → `preserve_config_for_upgrade`) operates
**only on `hooks-daemon.yaml`** — `settings.json` gets no merge at all.

The consequence: any customization a client makes to `.claude/settings.json` —
their own `statusLine` command, an extra hook they registered, a `permissions`
block, a deliberately-chosen `refreshInterval`, or any additional key — is
**silently clobbered on every upgrade** and reset to the daemon's values. This is
the footgun surfaced while shipping Plan 00175's `refreshInterval: 1` default:
that default rolls out *because* we overwrite, but the same mechanism means a
client can never keep a value of their own.

This plan designs and builds a **structured merge** for `settings.json` that
mirrors what already exists for `hooks-daemon.yaml`: the daemon keeps ownership
of the authoritative wired-hook forwarder set (Plan 00170) and ships recommended
defaults, while client-owned keys and deliberate overrides are preserved across
upgrades — with an **agent-assisted diff** path for the cases a purely mechanical
merge cannot resolve safely.

## Goals

- Client customizations in `.claude/settings.json` survive upgrades: extra hooks,
  a custom `statusLine`, a `permissions` block, extra top-level keys, and
  deliberate value overrides (e.g. `refreshInterval`) are all preserved.
- The daemon still guarantees delivery of its authoritative wired-hook forwarder
  set (Plan 00170) — an upgrade must never leave a client with a stale or
  incomplete `hooks` block.
- Recommended defaults (e.g. `refreshInterval: 1`) are applied on fresh install
  and offered on upgrade, but a client's deliberate override is not stomped.
- A safe fallback when the merge is ambiguous: surface a diff for
  human/agent resolution rather than silently choosing (the "agent-assisted diff"
  the user asked for), always failing toward *not destroying* client data.
- Full TDD coverage, QA green, daemon restart verified, docs + config-changes
  manifest updated.

## Non-Goals

- **Not** re-litigating the `refreshInterval` value (that shipped in Plan 00175);
  this plan is about *preservation*, using `refreshInterval` only as a worked
  example of a client-overridable default.
- **Not** changing `hooks-daemon.yaml` preservation — that already merges; this
  plan brings `settings.json` up to parity, reusing the pattern where possible.
- **Not** owning the client's Claude Code settings policy — the daemon owns only
  the wired-hook forwarder set and its recommended defaults; everything else is
  the client's.

## Context & Background

Key ownership is the crux. `settings.json` keys fall into three classes, and the
merge must treat them differently:

| Class                   | Examples                                                                                             | Merge rule                                                                                                                                                                  |
| ----------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Daemon-owned**        | the `hooks` forwarder set (Plan 00170 wired events)                                                  | daemon is authoritative — always deliver the current wired set; a client cannot drop or break a forwarder, but MAY add sibling hooks                                        |
| **Recommended default** | `statusLine.refreshInterval`, the default `statusLine.command`                                       | daemon ships a default; a client override (differs from the *old* default) is preserved (three-way merge); a client still on the old default is upgraded to the new default |
| **Client-owned**        | `permissions`, `plansDirectory` overrides, any extra top-level key, extra hooks beyond the wired set | always preserved verbatim                                                                                                                                                   |

Existing machinery to reuse / mirror:

- `scripts/install/config_preserve.sh` — the three-way merge workflow
  (diff old-default vs new-default vs user, merge, validate, report conflicts)
  already implemented for YAML via the `config-merge` daemon CLI command.
- The equivalent for `settings.json` needs a JSON three-way merge with the
  key-ownership rules above, plus (unlike YAML) a notion of the daemon-owned
  `hooks` block that is force-refreshed while sibling additions survive.

Open design questions to resolve during refine:

1. **Reuse vs new**: extend the `config-merge` CLI to a JSON/settings mode, or a
   dedicated `settings-merge` command? (YAML-merge assumptions may not port.)
2. **`hooks`-block strategy**: force-replace the daemon-owned forwarder entries
   by matching on the forwarder command basename (so client-added hooks in the
   same event array survive), vs. whole-block replace (simpler, loses sibling
   hooks). The Plan 00170 `_DAEMON_FORWARDER_HOOKS` SSoT is the authority for
   "which entries are ours".
3. **Agent-assisted diff trigger**: when does the merge escalate to a
   human/agent diff — only on validation failure / genuine conflict, or always
   present a summary of what changed? What is the non-interactive-install
   fallback (CI, headless)? Default must be *preserve, don't destroy*.
4. **Backup retention**: today install writes a timestamped `.bak`; upgrade
   Step 9 does a bare `cp` — confirm/likely add a pre-merge backup + rollback
   snapshot coverage (`scripts/install/rollback.sh` already snapshots
   settings.json).
5. **Interaction with Plan 00175's validator**: once overrides are preserved, the
   `statusline_refresh_checker` advisory (if built) becomes the right nudge for a
   client who kept a high value — warn, never force. Confirm the division of
   labour.

## Tasks

### Phase 1: Design & refine (looped audit)

- [ ] ⬜ **Task 1.1**: Resolve the five open design questions above; produce a
  decided key-ownership merge spec (which keys are daemon-owned / default /
  client-owned, and the `hooks`-block match-and-replace rule).
- [ ] ⬜ **Task 1.2**: Decide reuse-vs-new for the merge CLI and the
  agent-assisted-diff escalation contract (trigger + non-interactive fallback).
- [ ] ⬜ **Task 1.3**: Adversarial audit/refine pass (mirror Plan 00174's looped
  review) focused on data-loss safety and the shared-daemon / headless-install
  edge cases.

### Phase 2: TDD implementation

- [ ] ⬜ **Task 2.1**: RED — tests for the JSON three-way settings merge: client
  extra hook survives; custom `statusLine` survives; `permissions` survives;
  stale old-default `refreshInterval` upgrades; deliberate override preserved;
  daemon wired-hook set always complete after merge.
- [ ] ⬜ **Task 2.2**: GREEN — implement the settings-merge core (pure module,
  daemon CLI subcommand) with the key-ownership rules.
- [ ] ⬜ **Task 2.3**: Wire it into `install_version.sh` (Step 5) and both
  `upgrade_version.sh` deploy paths (Step 9), replacing the verbatim `cp` with
  a backup-then-merge; keep shellcheck clean.
- [ ] ⬜ **Task 2.4**: Agent-assisted diff path — on ambiguity/validation
  failure, emit the diff + guidance and preserve the client file (fail safe).

### Phase 3: Rollout, docs, QA

- [ ] ⬜ **Task 3.1**: End-to-end acceptance gates: fresh install applies
  defaults; upgrade with a customized settings.json preserves the customization
  AND refreshes the wired-hook set (mirror the H-1 install/upgrade gates).
- [ ] ⬜ **Task 3.2**: `config-changes`/upgrade-guide note; regenerate docs;
  reconcile with Plan 00175's validator.
- [ ] ⬜ **Task 3.3**: Full QA green, daemon restart RUNNING, 95%+ coverage.

## Technical Decisions

<!-- Filled during Phase 1 refine. Seed decisions: -->

### Decision 1 (seed): parity with hooks-daemon.yaml preservation

**Context**: `hooks-daemon.yaml` already survives upgrades via a three-way merge;
`settings.json` does not.
**Direction**: bring `settings.json` to parity with a JSON three-way merge rather
than inventing a different model — but account for the daemon-owned `hooks` block
which has no YAML analogue (it must be force-refreshed to the current wired set
while client sibling hooks survive). Final shape decided in Phase 1.

## Success Criteria

- [ ] Upgrade preserves: client extra hooks, custom `statusLine`, `permissions`,
  extra keys, and deliberate value overrides.
- [ ] Upgrade always delivers the complete current daemon wired-hook forwarder
  set.
- [ ] Fresh install applies recommended defaults; ambiguous merges fail safe
  (preserve client data) and surface an agent-assisted diff.
- [ ] Acceptance gates for install + customized-upgrade pass; full QA green;
  daemon RUNNING; 95%+ coverage; docs + config-changes updated.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Blow-by-blow lives in JOURNAL/00176-Journal-YY-MM-DD.md. -->

- Design authored (this PLAN.md); refine + implementation pending.

## Notes & Updates

- **Recovery cron**: `6ac90b2d` (session-wide non-durable failsafe) provides
  coverage; not duplicated for 00176.
- **Origin**: surfaced during Plan 00175 while confirming the installer copies
  the daemon's `settings.json` verbatim (`install_version.sh:363`,
  `upgrade_version.sh:664`). Sibling to Plan 00175 (which shipped the
  `refreshInterval: 1` default the overwrite currently force-applies).
