# Plan 00176: settings.json merge — preserve client customizations on upgrade

**Status**: Complete
**Created**: 2026-07-17
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

The installer and upgrader deployed the daemon's own `.claude/settings.json`
into client projects by **verbatim copy**, never a merge, from **three** routes:
`install_version.sh`, `upgrade_version.sh` Step 9, and `install.py` on every
invocation. So any customisation a client made — their own `statusLine`, an
extra hook, a `permissions` block, a deliberately-chosen `refreshInterval`, any
additional key — was silently reset to the daemon's values on every upgrade.

The surprise that shaped the design: a recoverable copy DID exist for the
upgrade route (Step 3's rollback snapshot), so the missing piece was never "back
it up first". A snapshot is a rollback artefact restored only on FAILURE; on a
successful upgrade the customisations were discarded, nobody was told, and the
copy expires after three more upgrades. Full measurements, the corrected backup
table and the `install.py` worked example are in
**[EVIDENCE.md](EVIDENCE.md)**.

This plan builds a **structured merge** for `settings.json` mirroring what
already exists for `hooks-daemon.yaml`: the daemon keeps ownership of the
authoritative wired-hook forwarder set (Plan 00170) and ships recommended
defaults, while client-owned keys and deliberate overrides are preserved across
upgrades — with an **agent-assisted diff** path for the cases a purely
mechanical merge cannot resolve safely. The rules are decided in
**[MERGE-SPEC.md](MERGE-SPEC.md)**.

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

- [x] ✅ **Task 1.4**: All four remaining audit findings resolved; evidence in
  the report, decisions in the spec.

  **Resolved**, each verified against the tree and written up in
  [MERGE-SPEC.md](MERGE-SPEC.md): the missing old-default baseline (**Q2b**),
  *absence is not an override* (**Q4b**), and the headless path having to FINISH
  rather than abort (**Q3**).

  The fourth — four unsynchronised writers — is **Q6**, where checking it
  changed the conclusion: the four do not share a failure mode, and a lock is
  not the first fix. With atomic writes the risk is a lost update, not
  corruption. The genuine conflict is `install.py`, which is not a race at all:
  it emits a fresh document rather than merging, so it discards a merge
  deterministically. That makes it Task 2.3's problem — the install route must
  go through the same merge as the upgrade routes, exactly as it now goes
  through the same backup helper.

### Phase 2: TDD implementation

- [x] ✅ **Task 2.1**: RED — every listed case plus the two invariants the
  ownership table implies. The discriminator rows are tested as the audit's
  probe stated them, including the ones a substring test got backwards: a
  client's `.claude/hooks/my-secret-scan`, a chained command, and a
  `$HOME/dotfiles/.claude/hooks/lint` are all left alone, while the relative
  legacy shape IS rebuilt anchored.

- [x] ✅ **Task 2.2**: GREEN — `install/settings_merge.py`. `merge_settings` is
  pure and deep-copies the CLIENT document; `run_settings_merge` is the file
  layer; `settings-merge` is the CLI the shell calls.

  `_build_hook_registration` became public `build_hook_registration` /
  `canonical_hook_entry`, so a rebuilt entry is byte-identical to a freshly
  installed one by construction rather than by review.

- [x] ✅ **Task 2.3**: All three routes go through it, and Layer 1 captures the
  Q2b baseline before its checkout. Two decisions worth carrying:

  With no interpreter the deploy **refuses** rather than falling back to the
  copy — that fallback is precisely the data loss this task removes. An
  identical file returns before that check, so the commonest case of all does
  not escalate for want of a tool it never needed.

  **`install.py` cannot use the merge** — it runs before any venv exists. It
  gets the safety PROPERTY instead: read the client document first, then edit
  the daemon-owned parts. The stated limit is that a client hook sharing an
  array with a daemon forwarder is not preserved there, since separating them
  needs the discriminator and that file already hand-keeps a copy of the wired
  set. Recorded in its code and tests, not left to be found.

- [x] ✅ **Task 2.4**: On an unreadable client file or a merged result that
  fails validation: nothing is written, the proposal goes to a
  `.merge-proposal` sibling, and the warning names both paths plus the
  top-level keys that would have changed. An unparseable client gets NO diff
  rather than a fabricated one, and the diff is bounded to top-level keys
  because a warning nobody finishes reading is what this path exists to avoid.

  Exit code `3`, never `1`: a 1 means abort to the calling scripts, and
  aborting the fast path leaves new forwarders over old settings with no
  snapshot to roll back to.

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

- [x] ✅ **Task 3.1**: End-to-end acceptance gates in
  `tests/acceptance/test_install_sh_end_to_end.py` — fresh install applies
  defaults; an upgrade over a customised `settings.json` preserves the
  customisation AND refreshes the wired-hook set. Both pass.

  **The gate first passed vacuously, and the reason is worth keeping.** A
  deliberate mutation (`merged = dict(new_default)`, discarding the client
  document entirely) did not fail it. Two independent causes: the fixture
  clones the repo at **HEAD**, so an uncommitted mutation is invisible to it —
  which makes naive mutation-testing of this gate meaningless — and
  `print_success` writes to **stderr**, so an assertion reading only stdout
  sees nothing. Fixed by reading `stdout + stderr` and by asserting the merge
  RAN (`"Merged settings.json" in upgrade_output`) BEFORE asserting its
  outcomes; an outcome assertion alone passes when the merge never happened.

- [x] ✅ **Task 3.2**: `truth-changes/v3.63.0.yaml` written (three `{was, now}`
  entries). No `config-changes` entry: this plan changes `settings.json`
  handling, not the `hooks-daemon.yaml` schema that manifest tracks. No upgrade
  guide: nothing here is breaking — preservation strictly improves. Generated
  docs regenerated with no drift.

  **Reconciliation with Plan 00175's validator — a real conflict, resolved by
  NOT reusing it.** `validate_hook_commands` counts every `type: command` hook
  in a wired event array and reports >1 as a duplicate registration. That
  directly contradicts this merge's own rule that a client hook may legitimately
  share an array with a daemon forwarder. Had the merge validated with it, every
  client carrying an extra hook would have escalated permanently — "preserved
  but never merged" — which quietly lets the wired forwarder set rot, the exact
  failure this plan exists to fix. The gate above caught it.

  `merge_settings` therefore validates with its own `_validate_daemon_forwarders`
  (exactly one canonical daemon forwarder per wired event, indifferent to
  siblings). `validate_hook_commands` is deliberately left alone: it serves the
  session-start advisory, where Plan 00266 reasoned about that counting rule on
  purpose.

  **Follow-up left open (not in scope here)**: the two now encode different
  notions of "correctly registered", so a client with a sibling hook gets a
  clean merge and a session-start advisory warning about it. Reconciling that
  advisory is its own change with its own decision to make — it belongs to
  00266's rule, not to this one.

- [x] ✅ **Task 3.3**: Full QA green — 26/26, 19962 passed, coverage 95.2%,
  daemon RUNNING.

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

- [x] Upgrade preserves: client extra hooks, custom `statusLine`, `permissions`,
  extra keys, and deliberate value overrides.
- [x] Upgrade always delivers the complete current daemon wired-hook forwarder
  set.
- [x] Fresh install applies recommended defaults; ambiguous merges fail safe
  (preserve client data) and surface an agent-assisted diff.
- [x] Acceptance gates for install + customized-upgrade pass; full QA green;
  daemon RUNNING; 95%+ coverage; docs + truth-changes updated (no
  `config-changes` entry is due — see Task 3.2).

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when"). Blow-by-blow lives in JOURNAL/00176-Journal-YY-MM-DD.md. -->

- **Phase 1 — the design questions decided against the code, not in the
  abstract** (`aac3eb6b`, `f9d262ad`, `253c0f7a`, `ff1fae00`, `6cee2d00`). The
  four clobber routes were mapped first (`d23b836d`, `6a772acf`, `bc92e3a0`),
  which is what revealed that the two installers already disagreed and one of
  them was right.
- **Phase 2 — the merge itself** (`2020b6ef`, `4ec8582a`, `567e9bd0`,
  `07a400d4`), plus the two pre-merge clobber fixes shipped ahead of it
  (`cdacbc56`, `56a845ac` — `--force` was the one install that took no backup).
  The safety property is the DIRECTION of the copy: `merge_settings` deep-copies
  the CLIENT document and edits the daemon-owned parts, so anything it fails to
  reason about survives by default.
- **Phase 3 — the acceptance gate earned its cost immediately** (`64330de0`,
  `74f640c2`). It caught the merge's own write gate contradicting itself: the
  Plan 00175 validator would have escalated every client carrying a sibling
  hook. See Task 3.2.

## Notes & Updates

- **Recovery cron**: `6ac90b2d` (session-wide non-durable failsafe) provides
  coverage; not duplicated for 00176.
- **Origin**: surfaced during Plan 00175 while confirming the installer copies
  the daemon's `settings.json` verbatim (`install_version.sh:363`,
  `upgrade_version.sh:664`). Sibling to Plan 00175 (which shipped the
  `refreshInterval: 1` default the overwrite currently force-applies).
