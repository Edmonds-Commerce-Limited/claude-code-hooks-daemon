# Plan 00176: settings.json merge — preserve client customizations on upgrade

**Status**: In Progress
**Created**: 2026-07-17
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The installer and upgrader deploy the daemon's own `.claude/settings.json` into
client projects by **verbatim copy**, never a merge. On a fresh install the
client's existing file is backed up then overwritten
(`scripts/install_version.sh:383-391`); on **every upgrade** it is overwritten
again (`scripts/upgrade_version.sh:864-867`, Step 9 "Redeploying settings.json").
(Both citations re-checked and updated — the originals, `:357-363` and
`:663-665`, had drifted onto unrelated code.)
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

**A third clobber route, found by Plan 00250 and not in the two scripts above:**
`install.py`, on **every** invocation. `create_settings_json`
(`install.py:690`) and `create_daemon_config` (`install.py:768`) both open with
`if <file>.exists() and not force:` — but that is **not** an early return. The
body renames the existing file to `.bak` and then writes the default template
unconditionally:

```python
if <file>.exists() and not force:
    backup_file = ...
    <file>.rename(backup_file)
# ... default template written here regardless
```

So `force` only decides whether a **backup is taken**. There is no invocation
that preserves an existing config. Confirmed on a GitHub runner, which printed
`✅ Backed up existing hooks-daemon.yaml…` / `✅ Created .claude/hooks-daemon.yaml`
from a plain `install.py --self-install` with no flag. The `/hooks-daemon install` skill documents `--force` only as "Force reinstall over existing",
which reads as though omitting it is safe.

Measured against this repository, that drops `plansDirectory` (whose absence
trips `R-MARKDOWN-PLAN-SYNC`), a `permissions.deny` block guarding `/tmp`,
`/var/tmp` and `/dev/shm`, `enableArtifact: false`, and the statusLine
`refreshInterval` — then replaces 1188 lines of `hooks-daemon.yaml` carrying 128
enabled handlers. **And the replacement does not work**: the daemon refused to
start on that config with `Unknown field 'min_confidence_score' at: handlers.session_start.min_confidence_score`, because the template still
configures `yolo_container_detection`, a handler with no module left in `src/`.
Worked example and evidence in
[Plan 00250's RESEARCH-ci-install.md](../00250-ci-runs-the-blocking-acceptance-gates/RESEARCH-ci-install.md).

**Where the backup actually is** — the answer inverts what you would hope for.
Of the three routes, the one that repeats is the one with no backup:

| Route                                        | Backup before overwrite   |
| -------------------------------------------- | ------------------------- |
| `install_version.sh:385-387` (fresh install) | yes — `.bak-<timestamp>`  |
| `upgrade_version.sh:865` (every upgrade)     | yes — the Step 3 snapshot |
| `install.py` without `--force`               | yes — `.bak`              |
| `install.py --force`                         | **no**                    |

**Correction (verified, and it changes the cheap mitigation).** The upgrade row
previously read "**no** — bare `cp`", reasoning from the copy alone. The copy
does take no adjacent backup, but `upgrade_version.sh:544` creates a full state
snapshot at **Step 3**, long before Step 9, and `install/rollback.sh:162`
captures `settings.json` in it. `cleanup_old_snapshots "$DAEMON_DIR" 3` at
`:1192` keeps the three most recent, so the copy survives a *successful*
upgrade.

So a recoverable copy does exist, and "back it up first" would have added a
second one. What is actually missing is different, and worse in a quieter way:

- **The snapshot is a rollback artefact, not a preservation mechanism.** It is
  restored only by `cleanup_on_failure`. On a *successful* upgrade the client's
  customizations are silently discarded and nothing puts them back.
- **Nobody is told.** Step 9 prints `Redeployed settings.json` — a success
  message for an operation that may have just dropped their `statusLine`,
  their `permissions` block and their `plansDirectory`.
- **It expires.** Three more upgrades and the last copy is gone.
- **It is best-effort.** Snapshot creation failure only warns
  (`:549`) and the upgrade proceeds anyway.

The cheap mitigation is therefore **not** an extra backup but a truthful
message: when the deployed file differs from the one already there, say so and
name the snapshot path. Small, independent of the merge design, and it converts
a silent loss into a recoverable one.

**The two installers already disagree, and one of them is right.** For
`hooks-daemon.yaml`, `install_version.sh:434` KEEPS an existing config and
deploys the tracked `.yaml.example` only when there is none — exactly what this
plan wants. `install.py` embedded its own template and replaced the config every
time, and that copy had drifted far enough to generate a config the daemon
refused to load. Fixed, with a round-trip test through the real validator. A
single source for the default config would have made it impossible.

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
  **Caveat found later (Plan 00250):** "already merges" is true of the shell
  upgrade path only. `install.py` clobbers `hooks-daemon.yaml` on every
  invocation, flag or no flag, so this Non-Goal holds for
  `preserve_config_for_upgrade` but not for the third route below.
- **Not** owning the client's Claude Code settings policy — the daemon owns only
  the wired-hook forwarder set and its recommended defaults; everything else is
  the client's.

## Context & Background

Key ownership is the crux: `settings.json` keys fall into three classes —
daemon-owned, recommended-default and client-owned — and the merge must treat
each differently. The decided table, with the exact keys and the rule for each,
is in [MERGE-SPEC.md](MERGE-SPEC.md).

Existing machinery to reuse / mirror:

- `scripts/install/config_preserve.sh` — the three-way merge workflow
  (diff old-default vs new-default vs user, merge, validate, report conflicts)
  already implemented for YAML via the `config-merge` daemon CLI command.
- The equivalent for `settings.json` needs a JSON three-way merge with the
  key-ownership rules above, plus (unlike YAML) a notion of the daemon-owned
  `hooks` block that is force-refreshed while sibling additions survive.

The five open design questions this plan was filed with — reuse-vs-new,
`hooks`-block strategy, the agent-diff trigger, backup retention, and the Plan
00175 validator — are answered in **[MERGE-SPEC.md](MERGE-SPEC.md)**, which also
carries the decided key-ownership table Phase 2 builds against.

One thing worth keeping here, because "which hook entries are ours" has **two**
answers in the tree and the merge has to pick one:

- `_DAEMON_FORWARDER_HOOKS` (`install.py:321`) — used by the fresh-install path
  to emit the `hooks` block.
- `HOOK_EVENTS_IN_SETTINGS` (`utils/hook_registration.py`) — derived from
  `EventID` where `wired=True`, used by the daemon's own reconcile/validate
  paths. `_DAEMON_WRAPPER_FRAGMENT` in the same module is what tells a daemon
  forwarder from a client's own hook.

They are kept in step by a drift test rather than by being one object. The merge
should build on the `src/` pair, since it runs inside the daemon and
`install.py` is a standalone bootstrap script that cannot import it.

## Tasks

### Phase 1: Design & refine (looped audit)

- [x] ✅ **Task 1.1**: All five decided in **[MERGE-SPEC.md](MERGE-SPEC.md)**,
  read out of the code rather than assumed. Two of the questions turned out to
  be partly answered already:

  **Q2 is half-built.** `reconcile_settings_hooks` exists and is **additive
  only** — its docstring says present events are left untouched — so it adds a
  missing wired event but cannot repair one that is present and *stale*. That
  single row is the plan's "never leave a client with a stale or incomplete
  `hooks` block" goal failing today. The discriminator the replace needs is in
  the same module: `_DAEMON_WRAPPER_FRAGMENT` (`/.claude/hooks/`), already used
  to tell a daemon forwarder from a client's own hook.

  **Q4 is closed** by Task 2.0, and **Q5 is moot** — `statusline_refresh_checker`
  does not exist, so there is no division of labour to confirm.

- [x] ✅ **Task 1.2**: **Dedicated `settings-merge`**, not an extension of
  `config-merge`. The YAML path being YAML-bound is the weak reason; the strong
  one is that the merge RULE differs. `preserve_config_for_upgrade` answers one
  question uniformly ("did the user change this from the old default?"), whereas
  the `hooks` block must be force-refreshed *against* the user's copy — the
  exact inverse. That would be a second, contradictory mode inside a function
  whose contract is to preserve.

  Escalation contract: diff only on validation failure or genuine conflict,
  never as routine narration — an escalation shown every upgrade gets skipped.
  Headless fallback is **change nothing and say so**: keep the client file,
  write the proposed merge beside it, exit non-zero naming both.

- [x] ✅ **Task 1.3**: Adversarial audit run against the spec:
  **[report](subagent-reports/260908-merge-spec-audit-opus.md)**, verdict
  *request changes*, 7 critical. It did its job — it falsified the spec's
  central mechanism rather than confirming it.

  **Three were defects in SHIPPED code, verified here and fixed:**
  `settings_deploy.sh`'s final `cp` ran unchecked, so a failed deploy reported
  success and made the caller's `|| fail_fast` unreachable; there were **three**
  copy sites, not two, and `install_version.sh:390` kept its own unchecked pair
  (the pinning test was scoped to the file being fixed, which is how the third
  stayed invisible); and `settings.json.bak-<timestamp>` was not gitignored, so
  every upgrade left the client's settings in an untracked file.

  **Q2's discriminator was wrong and is rewritten.** A runnable probe showed the
  `/.claude/hooks/` substring failing in both directions — including a false
  NEGATIVE on the relative legacy shape the rule existed to repair.

- [ ] ⬜ **Task 1.4**: Audit findings shaping Phase 2; evidence in the report.

  **Resolved, both verified against the tree and written up in
  [MERGE-SPEC.md](MERGE-SPEC.md):** the missing old-default baseline (Q2b — the
  daemon's own `settings.json` IS its shipped default, so Layer 1 can hand it
  over pre-checkout, exactly as it already does for YAML), and *absence is not
  an override* (Q4b — two of the three keys a client could silently stop
  receiving are security controls, so presence must be merged three-way just
  like value).

  **Still open**: the headless abort has no rollback on the fast path; and four
  unsynchronised writers with no lock, one of which (`install.py`) rewrites the
  whole document and would undo a merge. Note `hook_command_migration.py:258`
  writes in place **deliberately** — it preserves the mode of a git-tracked
  file, which `Path.replace()` rewrites — so the fix there is
  atomic-plus-`copymode`, as `settings_repair.py` does, not a swap.

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

- [x] ✅ **Task 2.0b** (the same defect on the third route): `install.py`'s
  `create_settings_json` backed up under `if settings_file.exists() and not force` — so **`--force` overwrote an existing settings.json with no copy and
  no warning**, while a fresh install with nothing to lose got the backup. The
  branch was untested: every existing test passed `force=True` into an empty
  directory, so none ever reached it.

  The flag is **removed**, not corrected — the daemon rewrites this file every
  invocation, so forcing only ever skipped the safety step. A test asserts the
  parameter is absent. Backup naming is collision-proof now too.

- [x] ✅ **Task 2.0** (shipped ahead of the merge):
  `scripts/install/settings_deploy.sh`, called from both `upgrade_version.sh`
  sites.

  **Filed against Step 9; Step 9 was the safer site.** The idempotent fast path
  at `:307` copies silently and `exit 0`s at `:439` — before Step 3's snapshot
  at `:539` — so nothing stands behind it, while Step 9 runs after it. The
  unprotected copy is the one that runs most often.

  One function now serves both, because two sites doing one job differently is
  what produced the gap. Behaviour and tests: [MERGE-SPEC.md](MERGE-SPEC.md) Q4.

  The third route, `install.py`, is Task 2.0b above — all three now take a copy.

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
