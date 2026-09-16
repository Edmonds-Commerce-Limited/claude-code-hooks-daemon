# Plan 00421: security detectors and ci enforcement

**Status**: Not Started
**Created**: 2026-09-16
**Owner**: dev
**Priority**: High
**Recommended Executor**: Opus
**Execution Strategy**: Sub-Agent Orchestration

## Overview

**No `scripts/qa/check_*.py` runs in CI.** `.github/workflows/qa.yml` invokes
black, ruff, mypy, `run_pyright_check.py`, `pytest tests/`, `pytest .claude/project-handlers`, bandit, deptry, shellcheck and a handler-import
probe, and the comment at `qa.yml:120` states plainly why: `run_all.sh`
resolves its interpreter through the daemon's venv resolver, so it is a
self-install entrypoint and not a CI one. Every Detector in the security
register is therefore bound to CI only through a pytest wrapper that asserts
against the real tree — and `check_authored_path_stat.py`, the register's FIRST
row, has no such assertion. Its wrapper drives fixtures. Register row 1
satisfies the register's own stated obligation ("a Detector in `scripts/qa/`
wired into `run_all.sh`") to the letter and is not enforced at the gate at all.
That is a record of non-coverage being read as coverage, which is the class
this project has now hit repeatedly, and it is why this plan opens here rather
than with the seven Detectors it also owes.

This plan is the single successor carrying forward everything
[Plan 00412](../Completed/00412-jobs-recurring-work-and-security-review/PLAN.md)
specified and did not build. 00412 closes at the v3.65.0 release with its four
owner gates ruled on; the work those rulings make necessary lives here. The
rulings are the source of nearly every task below and each states the work it
requires — read them, not this summary:
[where a Defence lives](../Completed/00412-jobs-recurring-work-and-security-review/fable-defence-location-decision.md),
[what survives degraded mode](../Completed/00412-jobs-recurring-work-and-security-review/fable-degraded-mode-decision.md),
[the forwarder interpolations](../Completed/00412-jobs-recurring-work-and-security-review/fable-forwarder-interpolation-decision.md),
and [the dotted module path](../Completed/00412-jobs-recurring-work-and-security-review/fable-secret-guard-module-path-decision.md)
(which needs no code and is carried only as an authoring constraint).

The ordering is the argument. Building seven more Detectors on an unenforced
binding would reproduce the same defect at seven times the scale, so Phase 1
pins what makes a Detector binding before anything new is written; Phase 2 makes
the register state its own gaps, which clause 9.2 requires while a migration is
in flight; Phase 3 migrates the Runner-hosted rules; Phases 4 and 5 close two
ruled defects in shipped code; Phase 6 builds the seven unwatched classes.

## Goals

- **A Detector is binding, provably.** Three parts, pinned once and generically:
  a `TOOL_REGISTRY` entry in `scripts/qa/llm_qa.py`, a pytest wrapper asserting
  against the real tree so `pytest tests/` fails when the rule fires, and a
  `run_all.sh` step. One generic wiring test pins all three for every
  `check_*.py`, replacing per-Detector wiring tests.

- **The register states its own gaps.** Every class the project has found is
  either covered by a conforming Detector or carries a row naming the interim
  mechanism and the method 3.2 gap. No class is silently absent, and no
  test-shaped rule is listed as if it were a Detector.

- **Every Defence is a Detector in `scripts/qa/`.** The six test-shaped
  Defences and the Plan 00246 git guard migrate; the seven unbuilt classes land
  in that shape from the start. No new test-shaped Defence lands from here.

- **Two ruled defects in shipped code are closed.** The drift reporters speak
  on an unparseable config; the generated forwarder stops interpolating a baked
  path into a `${VAR:-default}` word, where `$` and a backtick execute.

- **Each new Defence fails against the pre-fix tree.** A Detector that cannot be
  shown red before its fix is not a Defence, and every phase below is required
  to demonstrate it rather than assert it.

## Non-Goals

- **Running `scripts/qa/run_all.sh` in CI.** It is a self-install entrypoint by
  construction (`qa.yml:120`). The binding this plan builds routes through the
  pytest wrapper, which CI already runs.

- **Deciding any per-class FIX that the 00412 rulings hold owner-gated.** Where
  a ruling says a class's remediation needs an owner decision, this plan builds
  the Detector and leaves the fix gated.

- **Building the per-handler degraded-mode follow-on.** It is handed back as an
  open decision (below), not as work.

- **Changing `secret_file_guard`, its config or its tests.** The fourth ruling
  is determinate: nothing needs to change. It survives here only as three
  authoring rules for whoever touches `scripts/qa/check_sensitive_content.py`.

- **Touching the plan index.** `CLAUDE/Plan/README.md` is maintained centrally.

## Open decisions this plan must get ruled

Recorded here because the degraded-mode ruling HANDED IT BACK as needing its
own owner decision. It is not built by this plan.

- **Per-handler degraded mode.** Run a handler with its own parsed `options:`
  block while the document as a whole is invalid, and honour `enabled: false`
  inside the safety net — making "degraded" a per-handler state rather than a
  daemon state, which Plan 00304 explicitly scoped out. The ruling notes this is
  what would honestly cover `secret_file_guard`, whose Plan 00272 text records
  "No agent escape hatch — this block is the only lift, and it is a human's
  edit" while degraded mode is exactly an agent-reachable escape hatch for it.
  That contradiction is real and is recorded, not resolved, by Phase 4. Any
  denying form of option C (a write-time guard on the config file) rides with
  the same decision.

## Tasks

### Phase 1: Make a Detector binding, and say so correctly

- [ ] ⬜ **Task 1.1**: The generic wiring test, RED first. One test asserting
  that every `scripts/qa/check_*.py` has a `TOOL_REGISTRY` entry in
  `scripts/qa/llm_qa.py` and a step in `scripts/qa/run_all.sh`. It imports the
  registry rather than running it — `venv_python()` is deliberately resolved at
  run time, not import time, precisely so a wiring test can import the module
  (`llm_qa.py:96-107`), so follow that route.

  **It goes red on three files today and that is the finding, not a defect in
  the test.** Measured against the current tree: 20 `check_*.py` files exist, 17
  appear in `run_all.sh`, and `check_github_urls.py`,
  `check_python_var_guidance.py` and `check_eacces_safe_predicates.py` are
  registered in `llm_qa.py` and absent from the script. Do not narrow the test
  to make it pass; Task 1.2 closes the three.

  It replaces per-Detector wiring tests. The pattern to copy is
  `test_handler_reference_check.py:357-378`, which already pins both facts for
  one check.

- [ ] ⬜ **Task 1.2**: Close the three files the wiring test names. Add a
  `run_all.sh` step for each, in the numbering and failure style the existing 17
  steps use. `CLAUDE/QA.md:39` calls `run_all.sh` "the single source of truth
  for which checks exist" while six tools have existed in `llm_qa.py` only and
  nothing tested parity — the measured proof that "wired into `run_all.sh`" and
  "runs at the gate" were already different facts.

- [ ] ⬜ **Task 1.3**: The real-tree assertion for check 25. Its wrapper drives
  fixtures only and is the sole register row not enforced in CI. Add the
  assertion the other four already carry
  (`test_declared_invariant_pairs_checker.py:757-788`,
  `test_dangerous_invocation_corpus_checker.py:186-192`,
  `test_fail_open_inventory_checker.py:418-433`,
  `test_security_downgrade_flag_checker.py:555-561`).

  **The assertion must be shown to have teeth**, not merely to exist: introduce
  the class's defect into the real tree on a scratch commit, observe `pytest tests/` fail, and revert. A green assertion over a clean tree proves nothing
  about what it would do over a dirty one.

- [ ] ⬜ **Task 1.4**: Correct the rule text in the four places it is wrong.

  The binding rule — reword "a Detector in `scripts/qa/` wired into
  `run_all.sh`" to the three-part binding in `CLAUDE/Security/README.md:89-98`,
  `CLAUDE/Routine/00001-security-review-full/ROUTINE.md:102-103` and Plan
  00412's Task 3.4 wording.

  The founding story — the failure that gets cited for why a check must be
  wired was `check_project_handler_tests.py`, not Plan 00244's (which is the
  path-agnostic generated-docs plan and added no checker), and **the exit code
  gated correctly throughout; only the summary line a reader consults was
  wrong** (`CLAUDE/development/LESSONS.md:106-130`). The misattribution stands
  in `test_git_spawns_are_bounded.py:16-19`,
  `test_subprocess_spawns_are_bounded.py:25-27` and `llm_qa.py:609`. Correct all
  three. The two test docstrings also carry a "why a test rather than a
  `scripts/qa/` checker" rationale that the ruling overturns; it goes with them
  in Phase 3.

### Phase 2: Register hygiene — record coverage and record the gaps

- [ ] ⬜ **Task 2.1**: Class 14 (`fetch-then-execute-unpinned`) gets its page
  and row. `check_security_downgrade_flags.py` is check 29, conforms in form,
  has a real-tree assertion, and appears nowhere in the register. The register
  under-reports a conforming Detector today — the opposite error from the rest
  of this plan and just as damaging to a reader who trusts the table.

- [ ] ⬜ **Task 2.2**: Interim gap rows. One row each for the six test-shaped
  Defences (classes 3, 5, 7, 9, 10, 15), the Plan 00246 git guard, and class 2
  (`guard-self-disablement-unwatched`, which is handler-hosted at
  `guard_config_drift` and `guard_config_commit_gate` — neither a Detector nor a
  test, firing at session start and at commit rather than at the QA entry
  point).

  **Each row's Defence cell names the actual mechanism and states the gap** —
  "interim: a Runner-hosted rule, non-conforming to method 3.2, Detector owed"
  — because a row that named a test as if it met the obligation is the row the
  00412 decision document rightly refused to write, and silence is what clause
  9.2 forbids. The register already takes this side: "a register that only
  recorded what its Detectors cover would describe the detectors, not the
  defects" (`README.md:114-117`). No enforcement is lost in the interval: every
  test-shaped Defence keeps gating `llm_qa.py all` and CI until its Detector
  lands.

### Phase 3: Migrate the Runner-hosted rules — one unit

The ruling requires this as ONE worklist unit rather than per class, because
several share resolvers. Split into tasks for execution, but no phase-level
partial landing: the shared module moves once.

- [ ] ⬜ **Task 3.1**: Relocate `tests/subprocess_ast.py` into `scripts/qa/` and
  migrate the two spawn guards with it — class 15
  (`test_subprocess_spawns_are_bounded.py`) and the Plan 00246 git guard
  (`test_git_spawns_are_bounded.py`), which both import it.

  **The relocation is the reason these three move together.**
  `pyproject.toml:103` sets `testpaths = ["tests"]`, and a script run as `python scripts/qa/x.py` has `scripts/qa` on `sys.path` rather than the repository
  root, so `tests.subprocess_ast` resolves under pytest only. The precedent for a
  shared module in that directory is `contract_allowlist.py`.

  Each guard becomes `scripts/qa/check_<name>.py` with a stable rule identifier
  printed with every finding, a JSON report shape, a summariser and a
  `TOOL_REGISTRY` entry, and a `run_all.sh` step. **The rule logic does not
  change** — that is the whole reason this is mechanical. The existing fixture
  tests stay as each Detector's wrapper and gain the real-tree assertion.
  Each guard's recorded blind spots (`Popen`, a variable-built argv, a
  non-literal `"git"` first element) move with its documentation; they are
  boundaries the Detector still has and the register still has to state.

- [ ] ⬜ **Task 3.2**: Migrate the remaining five: class 3
  (`test_path_mutated_execution_resolves_argv_by_name.py`), class 5
  (`test_qa_checks_report_their_denominator.py`), class 7
  (`test_argv_is_not_built_by_splitting.py`), class 9
  (`test_git_enumerated_content_consults_protected_set.py`) and class 10 (the
  publication-surface additions inside
  `tests/unit/handlers/pre_tool_use/test_sensitive_content.py`). Same shape as
  3.1, same real-tree assertion, same wrapper treatment.

- [ ] ⬜ **Task 3.3**: Flip each migrated class's interim row to a real row, one
  per Detector as it lands, and delete the 3.2 gap note from that row only.
  **The wiring test from Task 1.1 must be green after every flip** — a row that
  names a Detector nothing runs is the defect this plan opened with.

### Phase 4: Degraded mode — the five ruled items

Ordered as the ruling orders them: the cheapest link in the chain first,
because it is the one the original request did not see.

- [ ] ⬜ **Task 4.1**: Make the drift reporters speak on `parse_failed`.
  `compare_guard_config` returns `DriftReport(parse_failed=True)` when either
  document does not parse (`utils/guard_config_drift.py:184-185`), `has_drift`
  is False for that report (`:79-81`), and both consumers therefore render
  nothing (`handlers/session_start/guard_config_drift.py:177-178`,
  `handlers/pre_tool_use/guard_config_commit_gate.py:164`). **The two handlers
  built to watch this file are silent on precisely the line that degrades the
  daemon.**

  Make `has_drift` (or a sibling property) true on `parse_failed`, and have both
  renderers emit a line naming the unparseable document with the `git checkout HEAD -- .claude/hooks-daemon.yaml` remediation already used for drift. No
  verdict changes anywhere. The existing reasoning for the empty report
  (`:173-175`, "an advisory that fires wrongly every session is one that gets
  switched off") holds for a *no-baseline* case, not a *parse-failed* one: a
  working tree that does not parse against a HEAD that does is not a false
  alarm, and a project whose COMMITTED config is unparseable is already
  degraded, so the handler does not run and the line cannot fire every session.

- [ ] ⬜ **Task 4.2**: Give the degraded advisory its content. Today it says
  only "handlers may not be configured correctly" (`core/hook_result.py:1169-1170`).
  It must name the count and names of configured, enabled, deny-capable
  `PreToolUse` handlers that are NOT running, and say whether
  `HEAD:.claude/hooks-daemon.yaml` validates.

  **The second line is the only honest typo-versus-deliberate discriminator the
  system can offer**, and it turns the remediation from "fix the configuration"
  into "restore the file from HEAD". Volume is not the problem — every hook
  response, the status line, `status`, `check` and `config-validate` already say
  DEGRADED. Content is. The advisory must also state that the early return
  covers **every** event type (`daemon/controller.py:915-926`), not only
  `PreToolUse`: `Stop`/`SubagentStop` teeth, `PostToolUse` linting and
  `SessionStart` directives are all off too.

- [ ] ⬜ **Task 4.3**: A test in `tests/unit/daemon/test_controller_degraded_mode.py`
  that a `STATUS_LINE` event in degraded mode renders the degraded text. It is
  true today as a consequence of the `Status` branch of the wire form
  (`core/hook_result.py:571-584`) rather than of any decision anyone took, and
  the existing module exercises `PRE_TOOL_USE` and `POST_TOOL_USE` only
  (`:217-233`). The test pins it so a later change to that wire form cannot
  silently remove the warning.

- [ ] ⬜ **Task 4.4**: Add `CurlPipeShellHandler` and `DangerousPermissionsHandler`
  to `_degraded_mode_safety_net` (`daemon/controller.py:794-841`), each with a
  test mirroring `test_degraded_mode_still_blocks_destructive_git`.

  **Both pass Plan 00304's admission test and the three other candidates do
  not.** The net constructs a handler cold, so any option that can change a
  verdict means it would enforce something the project did not configure:
  `sed_blocker` has its blocking mode, `secret_file_guard` has glob
  extend/replace, `allowed_consumers` and `exclude_paths`, and
  `project_containment` has `allowed_external_paths`. (The request document's
  `chmod_world_writable` is a rule name; the handler is `dangerous_permissions`.
  `ProjectContext` is initialised before validation, so needing the project root
  is not a barrier — only options are.)

  Bounded to degraded mode, where `curl … | sh` and `chmod 777` are currently
  ALLOWED with a warning. One behaviour change: a project that set
  `enabled: false` on either sees a deny it turned off — the precedent's cost,
  already true of `destructive_git`, and the reason the decision above exists.

- [ ] ⬜ **Task 4.5**: A declared config-independence property on the three net
  members, plus the Detector that keeps the list honest, in `scripts/qa/` per
  Phase 1's binding. The Detector must: fail when a `PreToolUse` handler
  satisfying the admission test is absent from the net; fail when a handler IN
  the net has acquired an option; **read the admission property from a
  declaration on the handler rather than inferring it**, because verdict
  invariance is not inferable from source and Plan 00304 is right that the
  architecture does not track it; and fail when a declared handler's `__init__`
  requires arguments, since the net constructs cold and an unhonourable
  declaration is worse than none. It compares the declared set with the net's
  set and fails on asymmetry in either direction.

- [ ] ⬜ **Task 4.6**: Open the per-handler degraded-mode decision as a
  `DECISION-*.md` in this folder, stating the question, the `secret_file_guard`
  contradiction it would resolve, and what Plan 00304 scoped out. Getting it
  ruled is the deliverable; building it is not in this plan.

### Phase 5: Forwarder interpolation — option B across six sites

- [ ] ⬜ **Task 5.1**: The generator. In `build_relay_guard_block`
  (`src/claude_code_hooks_daemon/install/forwarder_generator.py`), replace the
  two `${VAR:-<baked path>}` sites at `:273` and `:280` with a plain
  double-quoted assignment of the escaped value followed by an expansion default
  referencing it by name — `_rl_bin_default="<escaped>"` then
  `_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-$_rl_bin_default}"`, and the same for
  the fallback events branch. The dynamic events branch at `:279` is untouched:
  its default word is composed of `$name` references only. Update the comment at
  `:257-260`, which becomes false.

  **Two failure classes are live at these sites and they are not equal.** `$`
  and a backtick are the "silent and remote" class — a command substitution runs
  every time the daemon is down. `}` is a fail-open: the resolved path is wrong,
  `-x`/`-S` is false, and the forwarder takes the legacy round trip. Both close
  in this one change.

  **Also do the sixth site**: `append_nc_socket_arg` (`:539-559`) interpolates
  the same fallback events directory raw into a double-quoted argument at
  `:558`. Plain context, the existing `_escape_for_double_quotes` is exactly
  right there, and it is not applied. It sits in a different function, which is
  why a `reaches` row over `build_relay_guard_block` could never see it.

- [ ] ⬜ **Task 5.2**: Regenerate the 27 guarded forwarders under `.claude/hooks/`
  and commit them in the same change as 5.1. They are generated output compared
  byte-for-byte against a fresh generation (`test_hook_scripts_match_installer`).
  Existing `HOOKS_DAEMON_*` overrides keep their precedence, so no operator sees
  a behaviour change.

- [ ] ⬜ **Task 5.3**: Update the tests that pin the old shape.
  `tests/unit/install/test_forwarder_generator.py` asserts the literal
  `_rl_bin="${HOOKS_DAEMON_RELAY_BINARY:-/proj/…}"` line at `:403`, `:409`,
  `:429` and `:825`; the `_GUARD` fixture in
  `tests/unit/install/test_forwarder_root_normalisation.py:54-59` embeds it; and
  the docstring of `test_a_default_value_expansion_still_exposes_a_baked_path`
  says the line is "exactly how the relay binary path is baked", which stops
  being true — **the scanner rule that test exercises remains correct and
  remains wanted**, only its docstring's claim about the generator changes.
  `test_guard_block_env_overrides_are_pure_parameter_expansion` (`:432-438`)
  must keep passing unchanged: option B adds a builtin assignment, not a spawn.

- [ ] ⬜ **Task 5.4**: The Defence, and it must be an effect test.

  **Effect, not call.** Generate the guard block and the nc-rung call line for
  an `untracked_dir`, `project_root` and `relay_binary` whose text carries each
  of `$`, a backtick, `"`, `\`, `}`, a space and a glob character; execute the
  resulting assignment lines under `bash` twice — with `HOOKS_DAEMON_RELAY_BINARY`
  and `HOOKS_DAEMON_EVENTS_DIR` unset, then set to sentinels — and assert
  `_rl_dir`, `_rl_bin` and `_rl_events_dir` equal the intended path,
  respectively the sentinel, byte for byte.

  **Shape over the artefact.** Assert no `${…:-…}` word in a generated block
  contains an absolute path literal. `_ABSOLUTE_PATH`
  (`forwarder_generator.py:342-344`) already reads that shape. This is the
  invariant option B creates and option A could not state: it moves the
  guarantee off the call graph, where a forgotten call looks exactly like a
  present one, and onto the artefact's text, where a scan is exact.

  **Both branches**: generate under a root short enough for the dynamic events
  branch and one long enough for the AF_UNIX fallback, so the baked
  `resolved_events_dir` site is exercised and not just `relay_binary`.

  **Red on reversion**: it must fail against today's generator (the
  reproduction in the ruling is the fixture), and a deliberate re-introduction
  of a raw `${VAR:-{literal}}` f-string must turn it red. If it cannot, it is
  not the Defence.

- [ ] ⬜ **Task 5.5**: The row and the register. A `reaches` row for
  `_escape_for_double_quotes` may be added, but **its `reason` must say what it
  proves** — that neither function has lost every call to the helper — because
  `reaches_helper` (`scripts/qa/check_declared_invariant_pairs.py:439-470`) is
  satisfied by one call anywhere in a function and is green today with two sites
  raw. The pair with teeth is `append_nc_socket_arg` ↔ `build_relay_guard_block`,
  red today and green after 5.1. Move
  `CLAUDE/Security/AsymmetricSiblingProtection.md:180-202` from "partially
  fixed" to fixed only once 5.1–5.4 have landed, and correct its text to record
  six sites, not five.

### Phase 6: The seven classes nothing watches

Each lands in the prescribed shape: `scripts/qa/check_<class>.py`, an inventory
or corpus YAML beside it where the class is inventory-shaped (the form classes
4, 6 and 14 took), a stable rule identifier printed with every finding, a
`TOOL_REGISTRY` entry and summariser, a `run_all.sh` step, a
`tests/unit/scripts/test_<name>_checker.py` carrying the fixtures AND the
real-tree assertion, a `CLAUDE/Security/<Category>.md` page with its blind-spot
section, and a register row. Classes 4, 6 and 14 already paid this cost end to
end, so the pattern is established rather than invented.

Each task's Detector must be shown RED against a real instance of its class
before any fix lands. Where the class's representative fix is owner-gated, the
Detector lands and the fix does not.

- [ ] ⬜ **Task 6.1**: Class 8, `exemption-scope-drift`. An exemption written for
  one dialect applied in another, or widened past what it was justified for.

- [ ] ⬜ **Task 6.2**: Class 11, `check-enumerates-from-the-registry-it-polices`.
  A check that derives its denominator from the same declaration it is meant to
  audit, so an undeclared item is invisible to it.

- [ ] ⬜ **Task 6.3**: Class 12, `write-time-guard-with-no-batch-equivalent`. A
  guard that fires on a single write and has no counterpart on the batch route
  that reaches the same outcome.

- [ ] ⬜ **Task 6.4**: Class 13, `executable-content-outside-the-lock`. Code that
  executes during build or install from a source the lockfile does not pin.

- [ ] ⬜ **Task 6.5**: Class 16, `response-trusted-beyond-the-request-validated`.
  A fetch whose response is trusted further than the request was validated —
  the seed rule being a `urlopen` with no redirect handler constraining a scheme
  change.

- [ ] ⬜ **Task 6.6**: Class 17, `authored-or-argument-path-resolved-without-containment`.
  The containment half of the completed `authored-path-resolution` category,
  which that register page's own "the rule forces the chokepoint; it does not
  choose the helper" bullet names as outside what check 25 grades.

- [ ] ⬜ **Task 6.7**: Class 18, `tri-state-default-favours-capability`. A
  three-state gate mapping "unset" onto the same branch as "enabled" for an
  action that increases reach. The Detector hypothesis is over
  `src/claude_code_hooks_daemon/config/models.py`: find `bool | None` option
  fields and assert each one's consuming code maps `None` to the
  lower-capability branch, with a declared exception list.

## Success Criteria

Every criterion below is a thing that can be run and observed. None is ticked
on assertion.

- [ ] The wiring test exists and has teeth: adding a `scripts/qa/check_*.py`
  with no `TOOL_REGISTRY` entry, or with no `run_all.sh` step, makes `pytest tests/` fail. Demonstrated by doing both on a scratch commit and pasting the
  failure into the journal.

- [ ] The count of `scripts/qa/check_*.py` files equals the count of distinct
  check scripts invoked by `scripts/qa/run_all.sh`, and equals the number of
  `TOOL_REGISTRY` entries backed by a check script — asserted by the wiring
  test, not counted by hand.

- [ ] Every row in `CLAUDE/Security/README.md` whose Defence cell names a
  `scripts/qa/` Detector has a wrapper that asserts against the real tree, and
  for each one, reintroducing that class's defect into the tree makes `pytest tests/` fail. Demonstrated row by row, `check_authored_path_stat.py` included.

- [ ] Every row whose Defence is NOT a conforming Detector says so in the row
  itself, naming the mechanism and the method 3.2 gap. Verified by reading the
  table against the class list: no class present in the 00412 worklist is absent
  from the table, and no test-shaped rule is listed as a Detector.

- [ ] `tests/subprocess_ast.py` no longer exists at that path, both spawn rules
  run as `scripts/qa/` Detectors, and each can be invoked over a single file
  (detector specification 5.2) and prints an identifier `bin/hooks-daemon explain-rule` resolves offline.

- [ ] A working tree whose `.claude/hooks-daemon.yaml` does not parse, against a
  HEAD whose copy does, produces a named advisory at session start and at the
  commit gate. Demonstrated by breaking a scratch copy and capturing both.

- [ ] The degraded advisory names the count and the names of the deny-capable
  `PreToolUse` handlers that are not running, and states whether HEAD's config
  validates. Demonstrated from a real degraded daemon, not a unit fixture.

- [ ] In degraded mode, `curl … | sh` and `chmod 777` are DENIED, and a
  `STATUS_LINE` event renders the degraded text. Three tests, each of which
  fails if its handler is removed from the net.

- [ ] The config-independence Detector goes red when a net member gains an
  option, when a qualifying handler is left out of the net, and when a declared
  handler's `__init__` takes arguments. Three deliberate breakages, three reds.

- [ ] The forwarder Detector fails at the commit before Task 5.1 and passes at
  the commit after. Demonstrated by running it at both, with the hashes
  recorded.

- [ ] A generated forwarder built from a `project_root` containing `$`, a
  backtick and `}` resolves `_rl_dir`, `_rl_bin` and `_rl_events_dir` to the
  intended bytes under `bash`, with the override variables both unset and set,
  and no `${…:-…}` word in any generated block contains an absolute path
  literal.

- [ ] Each of the seven new Detectors has been observed RED against a real
  instance of its class in this repository before its fix (or, where the fix is
  owner-gated, with the instance left in place and recorded in its register
  page's blind-spot section).

- [ ] The per-handler degraded-mode decision document exists in this folder and
  has been put to the owner. Ruled or not, it is on the record as a decision
  this plan raised rather than a gap it left.

- [ ] `./scripts/qa/llm_qa.py all` passes, the daemon restarts cleanly, and CI
  is green on a named sha.

## Delivery & Milestones

<!-- Curated milestones + delivery commit hashes only (git is the SSoT for
     "when" — do not add dates). The blow-by-blow activity log lives in
     JOURNAL/00421-Journal-YY-MM-DD.md — see CLAUDE/PlanJournalling.md. -->

- Successor to Plan 00412, which closes at v3.65.0 with its four owner gates
  ruled and its resulting work unbuilt.
