# Plan 00336: upgrade path residual findings

**Status**: In Progress
**Created**: 2026-09-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Sonnet
**Execution Strategy**: Sub-Agent Orchestration

## Overview

A client's v3.61.0 → v3.62.0 upgrade produced a six-defect field report. All
six are fixed and shipped (commits `b1217789`, `a9866261`). This plan carries
the residue: four findings that surfaced while fixing them, each deliberately
left out of that change because it is a design question rather than a defect
repair, and one of which the field report itself raised as an observation
rather than a defect.

Two of the four are behavioural and matter more than their "follow-up" framing
suggests. Item 2 in particular means the config-preservation baseline is
computed against the wrong side of the version boundary on the documented
upgrade path, so changed defaults may never reach users who had accepted the
previous ones — that is a silent, ongoing effect on every client, not a
one-release accident.

Items 1, 3 and 4 are smaller: an efficiency and structure question in the
upgrade orchestrator, a stale-guidance window immediately after upgrading, and
a documented bootstrap command that this project's own new handler denies.

## Goals

- Establish whether the config-preservation "old default" baseline is wrong on
  the Layer 1 path, and if so make the diff compare against the version being
  upgraded FROM.
- Decide and implement the shape of Layer 2's post-checkout recovery: keep the
  current full second pass, or resume at Step 7 with an explicit state
  handover.
- Close the window in which a project's resident agent guidance describes the
  pre-upgrade version.
- Remove the contradiction between the documented bootstrap fetch and
  `project_containment`.

## Non-Goals

- Re-fixing any of the six defects already shipped — they have tests and are
  verified live.
- Rewriting historical upgrade guides under `CLAUDE/UPGRADES/v3/`. Those record
  what a past upgrade looked like; editing them would falsify the record.
- Changing `settings.json` merge behaviour — that is Plan 00176's scope.

## Tasks

### Phase 1: The config-preservation baseline (highest value)

- [x] ✅ **Task 1.1**: Confirm the finding and pin it with a failing test.
  **Done.** `scripts/upgrade.sh` checks the target out and only then invokes
  Layer 2, never copying `.claude/hooks-daemon.yaml.example` beforehand, so
  Layer 2's Step 5 copies the NEW default under a comment claiming it is the
  old one. `tests/integration/test_upgrade_old_default_baseline.py` pins the
  contract: 7 of its 9 tests were RED before the fix.
- [x] ✅ **Task 1.2**: Establish the consequence empirically rather than by
  reasoning. **Done — measured, and it is real.** Driving `ConfigDiffer` and
  `ConfigMerger` directly with a default that changed between versions
  (`log_level` `INFO` → `WARNING`) and a user who simply accepted the old one:
  against the true old default the value is not a customisation and the merge
  yields `WARNING`; against the new default it is recorded as
  `custom_daemon_settings = {'log_level': 'INFO'}` and the merge yields
  `INFO`. A changed default does not reach a user who had accepted the
  previous one. Evidence in the journal.
- [x] ✅ **Task 1.3**: Fix it. **Done.** Layer 1 preserves the example config at
  a new Step 3c — alongside the existing `FROM_VERSION` capture, which already
  exists for exactly this deadline — and exports
  `HOOKS_DAEMON_OLD_DEFAULT_CONFIG`. Layer 2's Step 5 now calls a new
  `resolve_old_default_config()` in `install/config_preserve.sh`, which prefers
  the handover and otherwise falls back to the on-disk example, so BOTH entry
  points end up with a true old-version baseline and the direct-invocation path
  is unchanged. The copy is kept outside `DAEMON_DIR` because Layer 1's
  checkout is a `reset --hard` for a normal install and would discard it.
  Rejected the `git show <previous-ref>:...` alternative: on the Layer 1 path
  Layer 2 no longer knows the previous ref, so it would need the same handover
  anyway — one mechanism beats two.

### Phase 2: Layer 2 post-checkout recovery shape

- [x] ✅ **Task 2.1**: Decide between the shipped full second pass and a
  resume-at-Step-7 design. **Decided in Task 2.3 — keep the second pass.**
  The state crossing the checkout boundary is small and known:
  `SNAPSHOT_ID`, `CONFIG_BACKUP`, `OLD_DEFAULT_CONFIG`, `CURRENT_VERSION`
  (`ROLLBACK_REF` is recomputable). The cost of resuming is restructuring
  Steps 1-6 into a skippable region in a 1200-line script that upgrades every
  client; the cost of not resuming is doing the work twice on a direct Layer 2
  invocation — which is the path the Defect 4 documentation fix steers people
  away from. See Task 2.3 for the evidence and the rejected alternative.

- [x] ✅ **Task 2.2**: Rollback contract. **Resolved by not resuming** — the
  second pass runs only after Step 17, with the upgrade already successful and
  `UPGRADE_STARTED=false`, so no snapshot has to cross the boundary. Verified
  separately that `exec` does not fire the EXIT trap, so the re-exec cannot
  trigger a spurious rollback.

- [x] ✅ **Task 2.3**: Record the decision. **Done — KEEP the second pass.**
  The gap it leaves is narrower than it first appeared, because under Layer 1
  (checkout at line 440, Layer 2 invoked at 478) Layer 2 starts as a fresh
  process AFTER the checkout, so its script body AND its sourced
  `install/*.sh` libraries are all the new release. The "steps run from old
  code" problem is therefore confined to DIRECT Layer 2 invocation — the path
  the Defect 4 documentation fix now steers people away from — and the second
  pass already covers new steps there. A blanket re-source of the libraries
  after checkout was considered as a cheaper alternative and REJECTED:
  `gitignore.sh` and `rollback.sh` declare `readonly` variables, and
  re-assigning a readonly under `set -e` aborts the script.

- [x] ✅ **Task 2.4** (added): Boundary of what the first pass runs as old
  code. Only the SHELL is stale. Step 7 rebuilds the venv from the new
  checkout, so every `"$VENV_PYTHON" -m claude_code_hooks_daemon...` call from
  Step 8 onward already executes the new release's Python. A fix in
  `config_differ.py` reaches the upgrade that delivers it; a fix in
  `config_preserve.sh` does not.

- [x] ✅ **Task 2.5** (added, and the largest finding in this phase) — **OWNER
  RULING: leave it. Not a bug.** "Leave it — because post upgrade we are
  supposed to handle the config optimisation." Upgrading must NOT rewrite a
  user's config file; `/optimise` is the adoption path. Do not "fix" this
  later without re-reading the ruling below.

  The ruling is safe because a handler absent from a project config is
  **enabled**, which was the owner's follow-up question and is now proven
  rather than assumed:

  ```
  EventHandlersConfig().get_handler('absent')          -> enabled = True
  ...model_validate({'h': {'enabled': False}})         -> enabled = False
  ...same config, a DIFFERENT absent handler           -> enabled = True
  ```

  `EventHandlersConfig.get_handler()` (models.py:87) returns a bare
  `HandlerConfig()` for anything not present, and `HandlerConfig.enabled`
  defaults to `True` (models.py:61). models.py:214 states the same rule in a
  comment: "Not in config = use defaults (enabled)". The field report supplies
  the third confirmation — five handlers new in v3.62.0 were registered and
  firing in a client project whose config predated the release, and one of them
  denied a write, before `/optimise` had run.

  So a handler must be **actively configured `enabled: false`** to be off, and
  a new default-enabled handler activates on upgrade with no config change.
  The residual gap `/optimise` genuinely fills is the opposite case: a handler
  that ships default-DISABLED stays off, and nothing but the review surfaces it.

  Retained for context — **On a
  standard Layer 1 tag upgrade, config preservation and merging never run at
  all.** Layer 1 checks out first, so Layer 2's Step 2 finds
  `ROLLBACK_REF == TARGET_VERSION`, takes the idempotent fast path, and
  `exit 0`s at line 418. `preserve_config_for_upgrade` is called from exactly
  one place — line 861, Step 10 — which the fast path never reaches. Confirmed
  by grep: Layer 1 contains no config-merge call of its own, and the fast path
  (269-418) contains none either, though it IS otherwise comprehensive (venv,
  hooks, slash commands, skills, plan workflow, core docs, ccy, relay, restart,
  post-install checks).

  Judge the impact before acting: this is staleness, not data loss. The user's
  config is left untouched, and the Pydantic schema supplies defaults for keys
  that are absent, so behaviour still follows the new defaults at runtime — the
  config FILE simply never gains the new entries. The config-optimisation
  review may well be the intended mechanism for adopting new handlers. The
  question for the owner is whether the fast path skipping Step 10 is deliberate
  or an accident of where the early `exit 0` landed.

### Phase 3: Stale resident guidance after an upgrade

- [x] ✅ **Task 3.1**: **Half the finding as filed was wrong, and the half that
  survives is worse than described.** The `<hooksdaemon>` block in a project's
  `CLAUDE.md` IS regenerated on every upgrade: both upgrade paths call
  `restart_daemon_verified`, and `DaemonController.initialise()` runs the
  `ClaudeMdInjector` (controller.py:292) as a side effect of daemon startup.
  Nothing had to be added for it.

  `.claude/HOOKS-DAEMON.md` is the real gap, and it is not a window — it is
  permanent. `generate-docs` is called only from `install_version.sh` (Steps 13
  and 15), so the document describes the version the project was INSTALLED at,
  however many upgrades later it is read. `upgrade_version.sh` never called it
  on either path.

- [x] ✅ **Task 3.2**: Run it as part of the upgrade. **Done** —
  `generate-docs` added to BOTH paths of `upgrade_version.sh`: the idempotent
  fast path (which every Layer 1 client upgrade actually takes) and the slow
  path as a new Step 16.6. Placed AFTER the daemon restart so it documents the
  handler set that actually loaded, and degrading to `print_warning` rather
  than `fail_fast` — guidance is not worth aborting a completed upgrade for.
  Plan 00329 (post-upgrade report bloat) is unaffected: the addition is one
  line of output per path (`Generated: <path>`), not a report.
  Chose `generate-docs` over `regenerate-docs` deliberately: the latter also
  rebuilds a controller to re-run the injector, which the restart has already
  done, so it would duplicate agent-asset and directory-role syncs for nothing.
  Pinned by `tests/integration/test_upgrade_regenerates_handler_docs.py`
  (3 of 7 RED before the fix).

### Phase 4: The bootstrap fetch conflicts with `project_containment`

- [x] ✅ **Task 4.1**: Confirmed live, and the scope was **more than double**
  what this task described. Running the documented command in this session was
  denied by `R-WRITE-OUTSIDE-PROJECT-ROOT`, so this is observed rather than
  inferred. Driving every fenced shell line of the instruction corpus through
  the live `ProjectContainmentHandler` found **17 denied commands in 8 files**,
  not the 2 files filed:

  | File                                    | Sites |
  | --------------------------------------- | ----- |
  | `CLAUDE/LLM-UPDATE.md`                  | 4     |
  | `README.md`                             | 4     |
  | `CLAUDE/LLM-INSTALL.md`                 | 2     |
  | `docs/guides/GETTING_STARTED.md`        | 2     |
  | `CLAUDE/development/RELEASING.md`       | 2     |
  | `CLAUDE/CodeLifecycle/Features.md`      | 1     |
  | `.claude/skills/.../troubleshooting.md` | 1     |
  | `.claude/skills/.../bug-report.md`      | 1     |

  Two of those were found only because the scan was made CommonMark-correct: a
  naive "every \`\`\` toggles a fence" parser desynchronises on `RELEASING.md`,
  which shows a fence inside a fence, and silently skipped 40 lines — including
  the Step 14 release-verification stanza that writes four files into `/tmp`.
  That one fails in THIS repository, where the daemon is self-installed, so our
  own release process was instructing a command our own handler denies.

- [x] ✅ **Task 4.2**: Resolved in the direction that keeps the security
  property. Every fetch now lands in `untracked/scratch/`, preceded by
  `mkdir -p untracked/scratch`; the download-inspect-run sequence is unchanged,
  so fetch-review-run survives intact and no `curl | bash` was introduced.

  The two cases were assessed separately as instructed, and the conclusion is
  that they do **not** need different answers — which is a finding, not a
  shortcut:

  - **Update**: the daemon is by definition installed and enforcing, so a
    `/tmp` destination is denied every time. `ensure_scratch_dir` (Plan 00333)
    has already created `untracked/scratch/` and its ignore file.
  - **Install**: the premise "may have no repository yet" is contradicted by
    our own guide — `LLM-INSTALL.md` says "From your project root (must have
    `.git/`)", and the first thing it does is clone into `.claude/`. No daemon
    is running yet, so nothing blocks it either way; the in-repo destination is
    still the better one, because `untracked/` survives a container restart and
    is gitignored the moment the installer runs.

  Pinned by `tests/integration/test_documented_commands_are_not_self_denied.py`,
  which extracts the commands and puts them through the real handler rather
  than pattern-matching for `/tmp` — so it follows the handler's boundary if
  that ever changes, instead of drifting from it.

- [x] ✅ **Task 4.3** (added): The deployed `.claude/skills/hooks-daemon/` tree
  had drifted from its source under `src/claude_code_hooks_daemon/skills/`.
  `troubleshooting.md` still carried the `/tmp` spelling that the source had
  already moved off. Fixed at the source and redeployed; the test scans the
  SOURCE tree, because the deployed copy is a generated artifact that lags
  until a redeploy and `docs_qa`'s `generated_doc_hand_edit` already guards it.

## Success Criteria

- [x] The config-preservation diff baseline is the version being upgraded FROM
  on both entry points, pinned by a test that fails against today's code.
- [x] Layer 2's post-checkout recovery shape is decided, implemented and
  documented, with the rollback contract verified either way.
- [x] A project's generated agent guidance matches the installed version
  immediately after an upgrade completes — `HOOKS-DAEMON.md` now regenerated on
  both upgrade paths; the `<hooksdaemon>` block already was, via the restart.
- [x] No shipped document instructs a command that this project's own handlers
  deny — enforced by driving the corpus through the live handler, not by a
  pattern match that could drift from it.
- [ ] Full QA green (25/25) and the daemon restarted and verified before the
  terminal status flip.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00336-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Source: the six defects fixed in `b1217789`; re-exec argument fix in
  `a9866261`. This plan is the residue of that work.
- Dedupe scout checked 44 live plans and found none covering these four items.
  Plan 00291 is closest by source (also from a client upgrade failure) but its
  stated scope does not encompass them; Plan 00176 covers `settings.json`
  rather than `hooks-daemon.yaml`; Plan 00329 bounds post-upgrade report size
  rather than ensuring the guidance block is regenerated.
