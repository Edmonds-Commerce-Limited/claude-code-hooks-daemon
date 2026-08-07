# Plan 00199: planlib — plan-orchestrator tooling in the daemon

**Status**: Not Started
**Created**: 2026-08-07
**Owner**: joseph
**Priority**: Medium
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Teams

## Source

Specification: `untracked/hooks-daemon-plan-lib.md` (1,226 lines) — read it
before executing any phase. Assessment, integration points and objections:
[PROPOSAL-ASSESSMENT.md](PROPOSAL-ASSESSMENT.md).

## Overview

The daemon owns the plan **lifecycle**: `mkplan.bash` scaffolds folders, a git
config counter allocates numbers, `plan_qa_edit` lints `PLAN.md` at Write/Edit,
`plan_qa_commit_gate` enforces cross-file invariants at commit, journals are
advised. It owns nothing about what happens when a plan needs something **run**.
That half is hand-rolled per plan, per project, from a ~40-line safety preamble
copied by hand — and it diverges on every copy.

The failure class this addresses is **a control that reports success without
having done its job**. The originating incident: a `triage.bash` resolved its
repo root with `git rev-parse --show-toplevel`, which answers about the *cwd*
rather than about the script — so run by path from another checkout it operated
on the wrong repository, checksummed a missing file, and **exited zero**
(source §1.1).

The proposal offers three separable artefacts: a sourced bash library
(`_planlib.inc.bash`), its test suite (`test-planlib.bash`), and a QA handler
(`plan_script_qa`) enforcing that orchestrators are built on the library.

**This plan ships the first two and defers the third.** The library and suite
stand alone, and the codebase has *already* anticipated this file:
`config/models.py:544` and `plan_qa/model.py:431` both name `_planlib.bash` as
the motivating example for `extra_root_files`. The handler is deferred because
this repo has zero orchestrator scripts to gate (Decision 4).

## Goals

- Ship `_planlib.inc.bash` as a daemon-owned asset, so the correct behaviour of
  each safety-critical primitive is the only behaviour on offer
- Ship `test-planlib.bash` covering every primitive, with a negative control on
  each control and an explicit statement of what it cannot cover
- Deploy it via the existing plan-workflow mechanism, on install and both
  upgrade paths, verified in client mode rather than only self-install
- Add the `plan_workflow.scripts.*` seam with **no** default for `root_marker`
- Record a defensible position on `plan_script_qa` and its trigger conditions

## Non-Goals

- **`plan_script_qa` (proposal artefact 2)** — deferred, see Decision 4
- A plan-script *generator*, anything that runs plan scripts automatically, or
  inferring the delegate — the proposal rejects all three (§10)
- Retro-fitting the three existing in-the-wild variants of this library
- Bash 3.2 / macOS system bash, Windows, non-bash orchestrators (§11)

## Context & Background

Three findings shaped the phasing; evidence in PROPOSAL-ASSESSMENT §1-3.

- **The config already anticipates the file.** `extra_root_files`
  (`config/models.py:540-544`) exists so a project can place a sourced
  `_planlib.bash` at the plan root without the sweep flagging it a stray. If
  the daemon ships it, it belongs in the built-in `_EXPECTED_ROOT_FILES`
  (`plan_qa/model.py:306-314`) instead.
- **The deployment vehicle exists.** `_deploy_mkplan`
  (`install/plan_workflow.py:277-292`) already writes a daemon-owned bash asset
  into the plan directory, overwritten every upgrade "so audit fixes reach
  existing installs" — the exact ownership model a shared library needs, behind
  one gated site (`install/plan_workflow.py:348-387`).
- **The rule engine exists.** The proposal's §7.1 split (pure rules + thin
  handler, so CI needs no daemon) describes what `plan_qa/` already is: 30
  checks, stdlib-only but for `plan_qa/gitfacts.py:23-24`, `Protocol`-bound
  config, three stages, and a CI-able CLI — hence Decision 1.

## Tasks

### Phase 1: Test suite first (RED)

The suite precedes the library per repo TDD discipline. Decision 2.

- [ ] ⬜ **Task 1.1**: Create `test-planlib.bash` harness with `assert_eq`,
  `assert_contains`, `assert_not_contains`, tmpdir fixtures and a failure
  summary that exits non-zero
- [ ] ⬜ **Task 1.2**: Write failing tests for root resolution — deep subdir
  resolves the root; nested repo with no marker FAILS rather than escaping to
  the outer repo; inner repo WITH a marker resolves to itself; a worktree
  `.git` **file** bounds the walk
- [ ] ⬜ **Task 1.3**: Write failing tests for mode/leg semantics — a failing
  gather leg continues and is recorded by name; a failing deploy leg aborts;
  the leg runner refuses a mismatched mode
- [ ] ⬜ **Task 1.4**: Write failing tests for the change gate and the backstop
  — a deploy-mode command is refused before the gate passes, and the refusal
  names `plan_gate_change`
- [ ] ⬜ **Task 1.5**: Write failing tests for delegation — argv is built as an
  array and never re-derives credentials
- [ ] ⬜ **Task 1.6**: Write failing tests for the pure predicates —
  `_plan_fingerprint_present` (space-delimited, so `SHA256:AA` must not match
  `SHA256:AAA`) and `_plan_strip_cr`
- [ ] ⬜ **Task 1.7**: Add the exit-deviation pin — assert that exactly
  `plan_deploy_leg`, `plan_finish` and `plan_parse_common_flags` call `exit`,
  so a fourth cannot grow one unnoticed (§3.12)
- [ ] ⬜ **Task 1.8**: Add a negative control for every control: perturb ONE
  thing and require exactly the expected assertion to fail

### Phase 2: The library (GREEN)

Carry the load-bearing comments verbatim — they are the ones that stopped
being copied. Inventory: ASSESSMENT §6.

- [ ] ⬜ **Task 2.1**: Header, source guard, `PLANLIB_VERSION`, and the
  configuration seam (`PLANLIB_ROOT_MARKER` with **no** default,
  `PLANLIB_PLAN_DIR`, `PLANLIB_DELEGATE`, `PLANLIB_SCRUBBER`)
- [ ] ⬜ **Task 2.2**: `_plan_err` / `_plan_banner` with the `|| return 1`
  convention documented as errexit-safety, not style
- [ ] ⬜ **Task 2.3**: `_plan_find_repo_root` + `plan_init` (source §3.3-3.4)
- [ ] ⬜ **Task 2.4**: `plan_mode`, `plan_gate_change`,
  `_plan_assert_change_allowed` — gate on state change, never target name (§3.8)
- [ ] ⬜ **Task 2.5**: `plan_start_log`, `_plan_finalize_log`,
  `_plan_on_signal` — the three subtleties of §3.5, and `wait` before scrub
- [ ] ⬜ **Task 2.6**: `_plan_scrub_log` + `_plan_quarantine_log` (§3.6)
- [ ] ⬜ **Task 2.7**: `_plan_tty_openable`, `_plan_strip_cr`, `plan_confirm` —
  the four traps of §3.7
- [ ] ⬜ **Task 2.8**: `plan_deploy_leg` / `plan_gather_leg` with the
  `BASH_SUBSHELL` guard (§3.9)
- [ ] ⬜ **Task 2.9**: `plan_run`, `plan_load_ssh_keys` (ordering enforced at
  runtime, §6), `plan_list_reports`, `plan_finish`, `plan_parse_common_flags`
- [ ] ⬜ **Task 2.10**: Confirm every Phase 1 test passes; run `shellcheck` over
  the library with no suppressions

### Phase 3: Deployment and configuration

- [ ] ⬜ **Task 3.1**: Add the bundled template at
  `install/templates/_planlib.inc.bash` and extend `package-data` in
  `pyproject.toml:67-69` so wheel installs carry it
- [ ] ⬜ **Task 3.2**: Add `_deploy_planlib` to `install/plan_workflow.py`
  mirroring `_deploy_mkplan` — daemon-owned, overwritten every upgrade, but
  mode `0644`: the library is **sourced, not executed**
- [ ] ⬜ **Task 3.3**: Add `_planlib.inc.bash` to `_EXPECTED_ROOT_FILES`
  (`plan_qa/model.py:306-314`) so the sweep does not flag it and no project
  needs `extra_root_files` for it
- [ ] ⬜ **Task 3.4**: Update the two docstrings naming `_planlib.bash`
  (`config/models.py:544`, `plan_qa/model.py:431`) to the shipped filename
- [ ] ⬜ **Task 3.5**: Add the `plan_workflow.scripts` config model —
  `root_marker` (no default), `delegate`, `check_flag`, `force_color_var`,
  `scrubber`, `track_run_logs`; neutral examples only (ASSESSMENT §5)
- [ ] ⬜ **Task 3.6**: Add a `config-changes` manifest entry so the new options
  surface on upgrade, per the release workflow
- [ ] ⬜ **Task 3.7**: Deploy the guidance doc — canonical bootstrap (both
  `source-path` directives, and why archiving a plan otherwise turns CI red),
  the §5 skeletons, and the manual TTY checklist

### Phase 4: Verification

- [ ] ⬜ **Task 4.1**: Wire `test-planlib.bash` into the QA suite so the
  library is gated like any other asset
- [ ] ⬜ **Task 4.2**: Client-mode verification — `scripts/dummy-client-repo.sh create`, then confirm the library arrives at the plan root with mode `0644`
  on a fresh install AND on an upgrade from a prior version
- [ ] ⬜ **Task 4.3**: Confirm the plan-tree sweep does not flag the deployed
  library as a stray root file
- [ ] ⬜ **Task 4.4**: Full QA (`./scripts/qa/run_all.sh`) and daemon restart to
  RUNNING
- [ ] ⬜ **Task 4.5**: Walk the manual TTY checklist by hand — passphrase
  prompt ordering, no second prompt when a key is loaded, gate ordering and
  refusal, and Ctrl-C leaving a complete log

### Phase 5: Decide on `plan_script_qa`

- [ ] ⬜ **Task 5.1**: Record the deferral with its trigger conditions
  (Decision 4) so it is a decision, not an omission
- [ ] ⬜ **Task 5.2**: If a trigger fires, open a follow-up plan implementing
  the rules as `CheckSpec`s in the existing catalogue (Decision 1), starting
  with the six crisp rules only (PROPOSAL-ASSESSMENT §4)

## Dependencies

- Depends on: nothing. Blocks: a future `plan_script_qa` plan
- Related: Plan 00144 (supplies the catalogue artefact 2 should extend),
  Plan 00163 (same deployed-asset ownership pattern)

## Technical Decisions

### Decision 1: Extend the existing check catalogue; do not build a second rule engine

**Context**: The proposal (§7.1) specifies a new `_plan_script_rules.py`
importing nothing from the daemon, plus a thin handler — because the daemon
often sits in a git-ignored directory and so cannot be imported in CI.

**Options considered**:

1. **A separate `_plan_script_rules.py`, as proposed.** Honours the CI
   constraint literally. Costs a second check catalogue, `Finding` shape,
   report renderer, config block and CLI, permanently parallel to `plan_qa/`.
2. **Script rules as `CheckSpec`s in `plan_qa/checks/`.** Reuses `Stage`,
   `Finding`, `Level`, the allowlists, the three surfaces and the CLI. The CI
   constraint is already met: `plan_qa/` imports two symbols from the daemon
   (`plan_qa/gitfacts.py:23-24`) and is otherwise stdlib, with `Protocol`-bound
   config and standalone defaults.

**Decision**: Option 2, when artefact 2 is eventually built. The proposal's
rationale is sound but its premise is already satisfied here — it was written
against a project without `plan_qa`. Two parallel engines for rules that are
both "plan QA" is a straight DRY violation.

**Where the fit is imperfect**: `CheckContext` is plan-document-shaped. Script
content fits the existing `file_content` slot, but R12 needs a file **mode**
and no slot exists — one additive field, not a reason for a second engine.

### Decision 2: Tests precede the library, inverting the proposal's ordering

**Context**: The proposal orders artefacts by value — library (1), then suite
(3) — while its §12 adoption order ships them **together** as one step. The
team's suggested phasing was (1) → (3) → (2).

**Options considered**:

1. **Library first, suite after.** Matches the value ordering, but inverts the
   repo's mandatory RED-GREEN-REFACTOR discipline, and a suite written after
   the fact asserts what the code does rather than what it should — fatal here,
   where the whole point is primitives whose wrong behaviour looks like success.
2. **Suite first (RED), then library (GREEN).** Repo-standard TDD.

**Decision**: Option 2. The apparent conflict with the proposal is not real:
§12 treats the pair as one deliverable, and CodeLifecycle/Features.md requires
the failing test first. The negative controls (Task 1.8) are only meaningful
written before the implementation.

### Decision 3: Ship as `_planlib.inc.bash`, mode 0644, daemon-owned

**Context**: Three sub-questions — filename, mode, ownership.

- **Filename**: the codebase says `_planlib.bash` (`config/models.py:544`,
  `plan_qa/model.py:431`); the proposal says `_planlib.inc.bash`. Take the
  proposal's — `.inc.bash` signals "sourced, not executable", the distinction
  that makes the mode obvious. Both codebase mentions are prose examples with
  no runtime effect, so updating them is free (Task 3.4).
- **Mode**: `_deploy_mkplan` uses `0o755` (`install/plan_workflow.py:24`)
  because `mkplan.bash` is executed. This library is **sourced**, so `0644` is
  correct — reusing the mkplan constant would ship a misleading execute bit.
- **Ownership**: `mkplan.bash` is daemon-owned and overwritten every upgrade;
  `_TEMPLATE_.md` and the journal assets are client-owned and never
  (`install/plan_workflow.py:232-345`). This must be **daemon-owned** — the
  premise is that the correct implementation is the only one on offer, and a
  client-owned copy re-creates the per-copy divergence being eliminated.

**Decision**: `_planlib.inc.bash`, mode `0644`, daemon-owned, overwritten on
every upgrade, deployed via the existing gated decision site.

### Decision 4: Defer `plan_script_qa` until it has something to gate

**Context**: The proposal's artefact 2 enforces that orchestrators are built on
the library. Its §12 adoption order puts it second, in `warn`, seeded with a
`legacy_script_allowlist`.

**Options considered**:

1. **Ship it now in `warn`.** Completes the proposal. But this repo has zero
   orchestrator scripts: the enforcement surface is empty, the allowlist has no
   baseline to seed, the ratchet has nothing to ratchet, and all fifteen rules
   would be validated only by unit tests written from the same document that
   specified them — no independent signal.
2. **Defer with explicit triggers.** Artefacts 1 and 3 deliver full value
   without it, as the proposal itself states ("(1) alone is worth having").

**Decision**: Option 2. Deferral is recorded with triggers, not left implicit.

**Reopen when any of these is true**: at least one project has orchestrators
actually built on the shipped library, so the rules can be validated against
code not written from their own spec; or a second variant of the library
appears in the wild; or a `git rev-parse --show-toplevel`-class incident recurs
in a project that has the library available.

**When it is built**: start with the six crisp rules (R1, R2, R3, R5, R9, R12)
rather than all fifteen. R14 is not mechanically checkable and belongs in docs;
R15 needs project config that does not exist yet (PROPOSAL-ASSESSMENT §4).

## Why this might not be worth doing

Argued in full in PROPOSAL-ASSESSMENT §7. In summary: **the daemon would not
dogfood it** — this is a Python project whose plans ship Python and tests, not
orchestrators against live infrastructure, so unlike `mkplan.bash` this asset
would never be exercised by its own maintainers, and unused code rots
invisibly. The suite answers that for the *logic* but not the *deployment
path*. Secondary objections: a dozen primitives with subtle fd plumbing is
large for a first ship, and the real consumer is in another organisation while
this repo carries the maintenance.

**Where that lands**: it does not kill Phases 1-4 — the daemon already ships
`mkplan.bash` by this exact mechanism and the config already names this exact
file, so the alternative is not "no library" but "every project keeps
hand-copying one". It does harden two constraints (Tasks 4.2 and 4.5) and
independently supports deferring artefact 2.

## Success Criteria

- [ ] `test-planlib.bash` passes; every primitive covered; every control has a
  negative control; the exit-deviation pin holds at exactly three functions
- [ ] `shellcheck` is clean over library and suite with zero suppressions
- [ ] The library lands at the plan root at mode `0644` on a fresh client
  install AND on an upgrade, verified against the dummy-client fixture
- [ ] The plan-tree sweep does not flag the deployed library as a stray file
- [ ] `PLANLIB_ROOT_MARKER` unset is a hard error at `plan_init`, never a
  fallback
- [ ] The manual TTY checklist has been walked, results recorded in the JOURNAL
- [ ] Full QA passes and the daemon restarts to RUNNING
- [ ] The `plan_script_qa` deferral is recorded with its trigger conditions

## Risks & Mitigations

| Risk                                                          | Impact | Prob. | Mitigation                                              |
| ------------------------------------------------------------- | ------ | ----- | ------------------------------------------------------- |
| Run-log drain regresses; logs truncated at the tail           | High   | Med   | Task 1.x pins `wait`-before-scrub; invisible without it |
| Ships with the execute bit, inviting direct execution         | Med    | Med   | Decision 3 fixes `0644`; Task 4.2 asserts it            |
| Ansible/`shellscripts/` flavour leaks into defaults           | Med    | Med   | ASSESSMENT §5 lists each; Task 3.5                      |
| A future `plan_script_qa` grows a 2nd rule engine             | Med    | Med   | Decision 1, recorded before anyone starts               |
| Deployed but never dogfooded; a client finds the break        | High   | Med   | Tasks 4.2 and 4.5                                       |
| `_EXPECTED_ROOT_FILES` change breaks `extra_root_files` users | Low    | Low   | Sets layer additively (`plan_qa/model.py:443`)          |

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00199-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Plan authored against the proposal; artefacts 1 + 3 accepted, artefact 2
  deferred with triggers
