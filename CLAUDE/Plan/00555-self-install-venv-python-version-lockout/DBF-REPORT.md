# Defence Before Fix report: Plan 00555, untrusted venv interpreter

Branch `p555-dbf-fix`, worktree `/workspace/.claude/worktrees/p555-dbf-fix`. The last code commit
is `e59cfa07a`, and the commit that adds this report follows it. Line numbers below are at `879f6c66c` unless marked "at the Defence commit";
`f43d472fb` moves `paths.py` below line 963 by three lines. Later commits change tests,
configuration, one comment and the detector's file enumeration only. The conformance reviewer
reproduced the green run at the final tree: "0 violations (1024 files scanned)", exit 0, and 124
detector tests passing.

## Specification followed

Method specification **1.1.0, fetched** (`/root/.cache/defence-before-fix/spec/SPEC.md`). Companion
documents as printed by the refresh script: detector specification 1.0.0 and toolchain specification
0.2.0, both fetched.

When this report was drafted the cached copy did not exist; an offline run of
`refresh-spec.bash` resolved only the vendored snapshot, **1.0.1**. A networked run of the same script
then fetched 1.1.0. Sections 3.4, 3.5 and 4 of 1.1.0 are what this report is checked against. Nothing
on the branch records which version the practitioners who did the work had read.

## Toolchain

- **Declared toolchain: none.** The project has no machine-readable DBF declaration (toolchain
  specification clause 9.2). Nothing in `pyproject.toml` or the repository root names one.
- **Register.** The fetched `register.json` lists no Python toolchain and nothing for shell. Its
  multi-language detectors (Semgrep, ast-grep, CodeQL) were not used. The project already runs
  Semgrep (`scripts/qa/semgrep/`), and no recorded reason explains why it was not chosen. The detector
  had to judge a function by its own body across Python and Bash, and resolve gates by reading their
  bodies (`proven_gates`). That fits the house pattern for project-local detectors better than a
  pattern rule does.
- **Detector chosen:** a project-local Python script, `scripts/qa/check_venv_interpreter_trust.py`.
  It uses `ast` for Python and reuses the shell lexer of the sibling detector
  `check_signal_targets.py` (import at `:62-68`).
- **Commands:**
  - Listing and single-rule harness: `python scripts/qa/check_venv_interpreter_trust.py [--json]`.
    It runs both rules. There is no per-rule switch; the JSON carries `rule` per finding.
  - Detector fixture tests: `tests/unit/qa/test_check_venv_interpreter_trust.py`.
  - Project entry point: `./scripts/qa/llm_qa.py venv_interpreter_trust`.
  - Identifier resolution: each message ends with the doc path `CLAUDE/Security/UntrustedVenvInterpreter.md`
    (`check_venv_interpreter_trust.py:157`). `qa-rules.json:598-606` maps both rule ids.
- **Calibration assumed** (the project had recorded none for this class). It is written into the rule
  doc, which makes it the project's first record:
  - **Proof is per function.** A finding is cleared only by a `pyvenv.cfg` read plus a version
    comparison in the same function, by a call to a gate whose own body passes that test, or by
    importing the package without editing `sys.path`.
  - **Sweep scope.** Tracked first-party `*.py`, `*.sh`, `*.bash` and shebang files. Excluded:
    `tests/`, `fixtures`/`assets`, `.claude/worktrees/`, `untracked/` and vendored code (docstring at
    `:35-39`).
  - **"Cannot tell" passes.** A missing `pyvenv.cfg` or version, or a probe that prints none, is not
    judged as drift (fix-core report, "Gates").
  - **No exemption marker.**

## Defect and class

- **Originating instance:** `src/claude_code_hooks_daemon/daemon/paths.py` `_venv_interpreter_runs`
  (line 960 at the Defence commit). It was the resolver's liveness gate, and it probed only
  `python -c "import sys"`. After the system Python moved from 3.11.2 to 3.13.5 (INCIDENT.md, "What
  happened"), the py311 venv's `bin/python` ran 3.13. The venv still passed the probe and kept
  resolving. The daemon could not import itself, and the self-heal, which fires only when nothing
  resolves, never ran.
- **Class:** code that decides a venv interpreter is usable, or selects one, on evidence that still
  holds after the base interpreter changes minor version. That evidence is existence, the exec bit,
  `import sys` or `--version`. The code never compares `pyvenv.cfg`'s major.minor with the interpreter
  that will run.
- **Hazard:** a venv that cannot see its own site-packages is treated as live. The result is a start
  failure that the repair and self-heal paths never see. Here it locked the session out for hours,
  because the fail-closed guard denied diagnostics and the stop hook blocked every stop.

## Rule

The detector is the project-local script above. The rule is documented in
`CLAUDE/Security/UntrustedVenvInterpreter.md` and indexed in `CLAUDE/Security/README.md`.

| Identifier                 | Message (`:131-140`)                                                                                                   |
| -------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| `venv-exec-bit-trust`      | "`{call}` judges a venv interpreter usable by existence or exec bit; nothing compares its major.minor with pyvenv.cfg" |
| `venv-weak-liveness-probe` | "`{call}` is a liveness probe any Python passes; nothing compares the venv's major.minor with pyvenv.cfg"              |

**Width.** The rule reports two kinds of check on a venv interpreter:

- **Existence and exec tests.** Shell `[ -x/-f/-e ]`, `[[ ]]` and `test`. Python `.is_file()`,
  `.exists()`, `os.access` and `os.path.isfile/exists`.
- **Weak liveness probes.** A run as `-c "import sys"`, `--version` or `-V`.

A venv interpreter is any of these:

- a `bin/python`/`bin/python3` path;
- a variable bound from one, or from one of the three resolver functions (`:88-94`);
- a `venv*/bin/$var` path;
- a `python_path` read from venv metadata.

**Deliberate exclusions:**

- **Package import as proof.** A function that runs `<interp> -c "import claude_code_hooks_daemon..."`
  without editing `sys.path` is not reported. After a minor change that import fails, so it is a
  stronger check than a version comparison (`10e40faa2`; detector report, item 4).
  `venv.sh verify_venv` is not covered by this exclusion because it prepends `src` to `sys.path`.
- **Local shadowing in shell.** A shell `local`/`declare`/`typeset` shadows an outer interpreter
  binding (`0298f52c5`).
- **Out-of-scope directories:** `tests/` and the others listed under Toolchain.

**Next wider rule considered:** "any execution of a venv interpreter not obtained from the SSoT
resolver". It would catch hand-built `venv/bin/python` paths that run with no test at all. It was
**not built** because it needs cross-function data flow: following `$PYTHON` through assignments,
arguments and sourced files. A name-based approximation reports correct callers
(`UntrustedVenvInterpreter.md`, "The next wider rule"). This is referred to the owner under Decisions.

## Proof

- **Red on the originating instance and the tree:** `b0dbbe5e4` adds only the detector and its tests
  (`git show b0dbbe5e4 --stat`: `check_venv_interpreter_trust.py` +660, test file +683, nothing else).
  Its commit message reads "red on the tree, no instance fixed". The detector report records **64
  findings** on that tree, both at the first run and after the reconciliation
  (`261029-dbf-detector.md`, "Result on the tree"). `paths.py` `_venv_interpreter_runs` is the first
  row of the rule doc's instance table.
- **Fixture proof:** `tests/unit/qa/test_check_venv_interpreter_trust.py` held 117 passing tests at
  the reconciliation. They include `TestWidenedToMatchTheIndependentSearch` and
  `TestImportingThePackageIsTheVersionCheck` (`10e40faa2`). `TestShellLocalShadowing` was added later
  with 7 tests, 5 of them red first (`0298f52c5`).
- **Wired and still red:** `feab6a3c8` wired the check into the project's QA. Its message reads "Red
  on the tree by design (64 findings), no instance fixed". The red survives on its own in `b0dbbe5e4`
  and `feab6a3c8`.
- **Not re-run for this report.** I did not re-run the `b0dbbe5e4` detector against the main tree.
  The 64 figure is cited from the report and both commit messages.

## Independent search

The searcher ran before the rule existed and without sight of it. It read the class description only
and did not open `scripts/qa/check_*.py` or `scripts/qa/semgrep/` (`261029-dbf-independent-search.md`,
header). It wrote down eight forms first:

- weak probes;
- mtime or path caches;
- version-blind `venv-*` scans;
- hash or stamp freshness;
- hard-coded versions;
- untested version tags;
- "resolver returned something" as success;
- venv pointers.

It recorded 57 candidates: 29 "yes" by its total (30 by its own list), 11 "unsure", and the rest
"no".

- **Only text search could find:** the version-bearing spellings, the `import sys` probes, the
  `.python-cmd-cache` filename, the inventory of every file that sources the resolver, and the
  positive controls (`setup_worktree.sh` tag compare, `create_venv_at_path`).
- **Only reading could find:**
  - the `import sys` probe passes for a symlink to another minor;
  - the scan fallback is what picks the old venv once the fingerprint misses;
  - both cache invalidators are blind to a system change;
  - self-heal and repair are gated on "nothing resolves";
  - freshness is lock_hash or stamp only;
  - `validate_venv` and `client_validator` are not instances.
- **Instances the rule first missed, and the widenings** (`10e40faa2`):
  - `[[ … || ! -f "$PYTHON_CMD" ]]` continuations;
  - `venv-*/bin/"$name"` paths (`resolve_venv.sh:324`, `venv-include.bash:307`);
  - `meta["python_path"]` (`paths.py:1234-1235`).
- **Search items with no lexical signature** (13: items 11, 20, 21, 24-26, 29, 31, 34, 35, 39, 44
  and 47). These are root causes (c) to (f) and delegation. Each was examined for a widening and none
  was found (detector report, "The searcher's 29 'yes' items"). They were fixed by hand; see The
  original defect and Decisions.
- **The detector found what the search did not.** It found sites in about ten scripts that the search
  had matched but not read, all nine `upgrade.sh` tests, `paths.py:2977` and `cli.py:3319-3321,3899`.

## Sweep and count

- **Scope:** first-party Python and shell, the two languages the pattern occurs in, under the
  exclusions above. The scope also covers the frozen `CLAUDE/UPGRADES/v2/*/verification.sh` scripts.
- **Not covered:** shell embedded in `.github/workflows/qa.yml`. The search rated it "unsure" with
  low exposure, and the detector does not read YAML.
- **Total:** 64 findings at the Defence commit. 54 were real (7 of those with low exposure) and 10
  were classed false positives.
- **Narrowing applied:** only the package-import proof above. It removed five findings: both copies
  of `install.sh:430`, `init.sh:1702` and `client_validator.py:609`. The search had independently
  judged each "no".
- **The 10 "false positives" were not narrowed.** Each was later fixed at the site or resolved by a
  detector bug fix (see Fixes), so none remains excluded.
- **Count at the fix phases:** 62 at the start of fix-core, then 46, 16 and 0
  (`261029-dbf-fix-*.md`).

## Fixes

Every row of the rule doc's instance table carries a Fix commit. The changes in each:

- **Gates (`b51912cb8`).** One usable-interpreter gate per language:

  - `venv_interpreter_usable` (`src/claude_code_hooks_daemon/daemon/paths.py:963`) replaces
    `_venv_interpreter_runs`.
  - `venv_python_usable` (`scripts/lib/resolve_venv.sh:351`) is the Bash gate.

  Each gate probes the interpreter and compares the `pyvenv.cfg` major.minor with the running one.
  `GATES` (`check_venv_interpreter_trust.py:81-85`) names them, and `proven_gates` confirms both
  from their bodies.

- **Core sites, also in `b51912cb8`:**

  - the resolver scan, the keyed and metadata branches and `live_venv_realpaths`;
  - the `HOOKS_DAEMON_VENV_PATH` override and `resolve_venv_python_in_venv`;
  - `bin/hooks-daemon` and its template;
  - `init.sh` `_is_daemon_installed`.

- **Shell scripts:**

  - skill wrappers, both copies (`83fc85414`);
  - `debug_hooks.sh` and two QA runners (`ed51d5951`);
  - `upgrade_version.sh` (`e1a368063`);
  - `install/venv.sh` (`486b61a22`; `get_venv_python_version` deleted, it had no callers);
  - `install_version.sh`, `setup_worktree.sh` and `validate_worktrees.sh` (`9dc994c0f`);
  - `venv-include.bash` (`10b2732e0`).

- **Remaining findings:**

  - `cli.py` venv listing now keys on `pyvenv.cfg` (`f7145ae1d`, merged `9c7302566`);
  - `upgrade.sh` metadata and message (`dc650805b`);
  - `upgrade.sh:967`, a detector bug fixed by the shadowing rule (`0298f52c5`);
  - `rollback.sh` (`e0515c094`);
  - both historical `verification.sh` scripts (`d262dd275`);
  - `_probe_python_version` (`780babfad`).

- **Examined individually or by pattern:**

  - Examined individually: every Python site, the `upgrade.sh` block, `rollback.sh`, `venv.sh`,
    `venv-include.bash` and the historical scripts.
  - Changed by pattern (`[ -f/-x "$X" ]` becomes `venv_python_usable "$X"`): the six skill wrappers,
    `debug_hooks.sh`, the two QA runners, `upgrade_version.sh`'s five code sites, `install_version.sh`,
    `setup_worktree.sh` and `validate_worktrees.sh`.
  - The fix-shell report says each site was "run red first, then green" in
    `tests/integration/test_dbf_gate_shell_scripts.py` (24 tests).
  - `upgrade_version.sh` was tested statically only.
  - No separate sample of the by-pattern sites is recorded beyond those tests.

- **Red against the pre-fix code.** Fix-b ran fix-core's new tests at `6edb526c7`:

  - 11 of 14 failed in `test_paths_venv_gate_consumers.py`.
  - 5 of 9 failed in `test_dbf_gate_shell_consumers.py`.
  - One test was red for the wrong reason and was corrected.

  Fix-core's own tests were written after the code. That report says so.

- **No suppression, no baseline, no exemption marker.** The detector has none. The rule doc states
  "fix the site, or fix the Detector", and the final count of 0 was reached by site fixes and two
  detector bug fixes.

- **Regression found by the full gate (fixed in `f43d472fb`).** Moving `live_venv_realpaths` and
  `classify_untracked_venvs` onto the gate meant every `cmd_start`, which reaps stale venvs first,
  launched a probe for each candidate venv, including ones whose `bin/python` was absent. The full
  gate surfaced it in `tests/unit/daemon/test_cli_cmd_start.py`: 4 failures on 3.13, and a hang on
  3.11 and 3.12. That file's `os.pipe` patch held a probe's pipe. Main passes all 30 tests. The gate
  now refuses a missing interpreter or a dangling symlink without a probe
  (`test_the_gate_refuses_a_missing_interpreter_without_launching_it`, red first). Absence proves
  unusability, so this trusts no exec bit. Journal:
  `JOURNAL/2026-10-31/015955Z-finding-8d30e7.md` (on main).

- **Further full-gate failures, all caused by the branch (fixed in `707e50957`, `ae57ccdb8`,
  `5ad3529b8`).**

  - **Test fixtures that encoded the hazard.** Several fixtures built a "venv" whose `bin/python` is
    a stub that exits 1 or is a bare executable file, and relied on it being judged usable. That is
    the class itself, inside `tests/`, which the sweep excludes. Fixed by building the fixture from a
    symlink to the running interpreter plus a matching `pyvenv.cfg`:
    `test_client_validator.py` (`707e50957`) and the ci_passthrough `_create_installed_stub`
    (`ae57ccdb8`). This is evidence for Decision 3: the `tests/` exclusion hides fixtures that
    depend on the hazard, although none of them ships.
  - **Resolver stubs without the gate.** Tests that stub `scripts/lib/resolve_venv.sh` now define
    `venv_python_usable` or source the real library, because the wrapper calls the gate
    (`test_bin_wrapper_project_anchoring.py`, `707e50957`; the symlinked-project integration test,
    `5ad3529b8`).
  - **Stale exclusion.** The `verify_venv` entry in `error_hiding_exclusions.json` named a line the
    fix removed (`707e50957`).
  - **Contract assertions on changed text.** The debug_hooks socket test's end marker, the guidance
    doc's literal `$PYTHON` wording, and the release-gate workflow's `CHECKS_STATIC` list, which now
    carries `venv_interpreter_trust` (`ae57ccdb8`).
  - **Protected-path audit.** The detector enumerates with `git ls-files`, so the protected-set audit
    required it to drop protected paths itself (`_without_protected`, `5ad3529b8`). The scanned
    count is unchanged.

- **Default with a stated meaning.** In `rollback.sh`, a drifted venv's version is recorded from
  `pyvenv.cfg` as `3.11.2 (interpreter drifted)` and its `pip freeze` is skipped. The field has no
  reader beyond the manifest (`e0515c094`).

## Decisions referred to the owner

No owner is recorded for this class, so under the specification's default the owner is whoever
instructed the work. None of the decisions below has been taken.

1. **The rule is narrower than the independent search showed** (section 4, final bullet).
   - **What:** 13 "yes" items from the search fall outside the rule. They are root causes (c) cache
     invalidated by mtime only, (d) freshness by lock_hash or stamp, (e) self-heal and repair gated
     on "nothing resolves", (f) success meaning "resolved", and delegation through resolver shims.
   - **Count:** all 13 fixed by hand with tests (see The original defect); 0 left as instances.
   - **What stopped a rule:** none of them has a lexical signature. Each is a missing term or a branch
     condition's meaning, not a spelling.
   - **What remains for the owner:** the class is partly undefended. A regression in (c) to (f) is
     silent to the detector and caught only by the tests named below.
2. **The next wider rule is unbuilt** ("any execution of a venv interpreter not obtained from the SSoT
   resolver").
   - **Why:** it was rejected because it needs cross-function data flow and a name-based
     approximation produces false positives. Instances of the hazard do exist, so absence is not the
     reason. That makes it the same owner decision as item 1.
   - **What to try next:** a data-flow-capable detector, such as CodeQL for Python. The register rates
     it amber as a detector. Shell would still be uncovered.
   - **What it would take:** tracing values across sourced Bash files, for which no listed tool offers
     support.
3. **Assumed calibrations to confirm:** the `tests/` exclusion, the uncovered workflow YAML, and the
   "cannot tell passes" default in both gates.
4. **Merge state.** The rule became blocking on this branch at `feab6a3c8` while 64 instances were
   open. Clause 4 allows this only while the branch stays unmerged, and it has: the branch is not on
   `main`. It now reports 0, so it can merge at full width. No instance is recorded as known and
   unfixed.

**Out of class, found and not fixed:**

- `scripts/install/rollback.sh` `create_state_snapshot` (`:112`) never creates `files/venv/` or
  `files/gitignore/`. The writes at `:244`, `:246` and `:258` then fail silently on a real run, and
  the new test pre-creates the directory (`261029-dbf-fix-final.md`). Recorded as **N561** in the
  open niggles ledger (Plan 00474), fact-checked and corrected on main (`03d756315`).
- A `secret_file_guard` false positive. A read-only `grep` whose regex was `.*bin.*python` was denied
  as matching `.vault-pass*` (`JOURNAL/2026-10-29/120329Z-finding-332060.md`).

## Permanence

- **Wiring:**
  - Check 34 in `scripts/qa/run_all.sh:452-462` fails the run (`OVERALL_EXIT_CODE=1`) and feeds the
    summary at `:514`.
  - In `scripts/qa/llm_qa.py`, `venv_interpreter_trust` is a `ToolConfig` at `:741-743`, appears in
    the check list at `:957` and has a summariser at `:1320`.
  - `scripts/qa/qa-rules.json:598-606` holds both rule entries.
- **Green run through the entry point** (`./scripts/qa/llm_qa.py venv_interpreter_trust`, in the
  worktree at `879f6c66c`):

```
✅ venv_interpreter_trust: 0 violations (1024 files scanned)
QA: 1/1 PASSED
```

That run was at `f43d472fb`, and the full gate at `5ad3529b8` printed the same line.

**Full gate** (`./scripts/qa/llm_qa.py all` at `5ad3529b8`, about 3.5 hours, Python 3.11, 3.12
and 3.13): 40 checks passed. On Python 3.13 every unit and integration shard passed with 0 failures,
about 52,800 tests. The failures it reported, and what became of each:

- `inline_suppressions`: a `shellcheck disable` this branch added in `venv.sh` gave no reason. Fixed
  in `e59cfa07a`; the checker reports 0.
- `plan_qa`: a journal-freshness advisory about Plan 00554. Not part of this branch.
- 9 acceptance tests errored at setup with "no live socket". The worktree daemon was restarted
  during the run (the PID changed from 1816 to 382221). Run again against the live daemon, 9 of
  the 10 pass.
- The tenth is playbook probe #120 (WorktreeFileCopyHandler), which also fails in the 3.11 and 3.12
  legs. The probe sets `cwd` to `$MAIN_CHECKOUT_DIR`, which lies outside a worktree's project root,
  so `R-WRITE-OUTSIDE-PROJECT-ROOT` denies first. The branch changes no handler, core or acceptance
  file, and the same test passes on main. It fails for any branch whose gate runs in a worktree, so
  it is recorded as a niggle rather than fixed here.

## Toolchain and detector gaps

- **Stale remediation text (found while drafting, fixed in `f43d472fb`).** The failure remediation
  and the `qa-rules.json` fix text named `_venv_interpreter_runs`, which no longer exists, and
  `_rv_candidate_runs`, which is now a probe only. The remediation is now built from `GATES`
  itself, so it cannot drift from the gates again. The JSON names `venv_interpreter_usable`,
  `venv_python_usable` and `_rv_cached_venv_current`.
- **No per-rule selection.** The detector offers no single-rule switch; both rules always run.
- **No toolchain declaration.** The project declares no toolchain or spec version (toolchain
  specification 9.2), so no gap record exists either.
- **Lexical limits.** The detector is lexical and judges a function by its own body. Delegation, and
  causes (c) to (f), are outside what it can see (see Decisions 1 and 2).

## The original defect

**Conventional fix:** Task 2.2, merged onto the branch at `6edb526c7`.

- `e936d4538`: the Python and Bash resolvers compare `pyvenv.cfg` `version_info`/`version` with the
  running major.minor and refuse a drifted venv. `classify_venv` reports it stale.
- `8bfcf9ab1`: a hot-path cache hit must also pass `_rv_cached_venv_current`. This compares the cfg
  minor with the deepest `pythonX.Y` hop of the `bin/python` symlink chain, and fixes cause (c).
- `63703130d`, `ca1d25a9a`: QA fixes on that branch.
- `b51912cb8`: the DBF gate replaced `_venv_interpreter_runs` with `venv_interpreter_usable`.

**Tests that reproduce the defect and now pass:**

- `tests/unit/daemon/test_paths_venv_interpreter_drift.py`:
  - `TestInterpreterRuns::test_drifted_version_info_does_not_run`
  - `TestResolverFallsThroughOnDrift::test_metadata_step_rejects_a_drifted_venv` and
    `test_scan_step_rejects_a_drifted_venv`
  - `TestClassifyVenv::test_drifted_venv_is_stale_even_when_lock_hash_matches`
- `tests/integration/test_resolve_venv_interpreter_drift.py`:
  - `test_bash_and_python_agree_on_drift`, `test_pick_python_skips_a_drifted_venv`
  - (c): `test_cache_hit_refused_when_cfg_version_changes`,
    `test_cached_venv_check_refuses_when_system_python_link_changes`

**Non-lexical causes, by hand in `b51912cb8`:**

- (d): `_cli_check_venv_fresh` returns STALE for a venv that fails the gate, and
  `_write_venv_metadata` refuses to stamp one.
- (e): a drifted venv no longer resolves, so `_is_daemon_installed` is false and `_venv_self_heal`
  and the wrapper repair arm fire. `_repair_venv_locked` fails when the built minor differs from the
  fingerprint (`fingerprint_major_minor`).
- (f): `_vb_build_under_lock` is correct through the version-aware resolver.
- Tests: `tests/unit/daemon/test_paths_venv_gate_consumers.py` (14) and
  `tests/integration/test_dbf_gate_shell_consumers.py` (9). Fix-b ran them at `6edb526c7` and they
  were red there.
- The (f) tests (`TestBuildSuccessIsJudgedByTheVersionAwareResolver`) passed on the old code too, so
  they are a regression guard and not a reproduction. Fix-b says so, and so does the rule doc.
- `ensure_daemon` was not run end to end for (e); the chain is shown step by step (fix-core report).

**Plan state.** Task 1.1 and Task 2.2 are ticked in PLAN.md. The plan's other tasks (2.3 to 2.7,
Phase 3) are outside this DBF remediation.

## Conformance review

`defence-before-fix:conformance-reviewer` ran at `f5a225d4c`
([report](subagent-reports/261031-dbf-conformance-review.md)).

- **What it reproduced:** red at `b0dbbe5e4` (exit 1, 64 findings including `paths.py:960`) and green
  at the final tree (exit 0, 0 findings in 1024 files).
- **What it did not check:** the full gate. The reboot had cleared its spec cache, so it cited clauses
  by topic. The cache was then re-fetched (1.1.0).

Its findings, and what became of each:

1. **"The original defect was fixed first" (High). Refuted.**
   - Neither `e936d4538` nor `8bfcf9ab1` is an ancestor of `b0dbbe5e4`
     (`git merge-base --is-ancestor`), so the red ran against unfixed code.
   - The instance fix existed on a separate unmerged branch before DBF was engaged. It entered this
     branch only at the merge `6edb526c7`, after the defence was committed red and wired.
2. **The package-import exemption is not tied to the interpreter tested (High). Kept, as calibration.**
   - Every proof is judged per function, not per binding: the `pyvenv.cfg`-plus-version read and
     the gate call as well as the import. That is the recorded calibration ("Proof is per function").
   - Fixtures show the exemption still reports an import that prepends the source tree or edits
     `sys.path`, and an import of another module (`TestImportingThePackageIsTheVersionCheck`,
     `test_check_venv_interpreter_trust.py:760-794`).
   - The five sites it removed were judged "no" by the independent search.
   - Tightening every proof to a binding is the data-flow work in Decision 2.
3. **Fix tests were written after the code (Medium). Already disclosed.** The report says so above,
   together with the red run of fix-core's tests at `6edb526c7`. No further sample of the by-pattern
   sites was taken.
4. **Late loosenings rest on asserted false positives (Medium). Answered.**
   - `0298f52c5` is fenced by `TestShellLocalShadowing` (7 tests, 5 red first). These include the
     cases that stay reported: an unshadowed use, a local bound to an interpreter, and shadowing
     confined to one function.
   - `5ad3529b8` changes no judgement. It drops protected paths from enumeration, which the
     protected-set audit requires, and the scanned count is unchanged at 1024.
5. **The owner referrals are unresolved (Medium). Correct, and not ours to resolve.** Decisions 1 to 3
   above stand for the owner. The class is recorded as partly defended, and nothing is baselined or
   suppressed.
6. **The green run is stamped at older commits (Low). Resolved.** The header now records the
   reviewer's green run at the final tree.
7. **`shellcheck disable` reasons in `venv.sh` (Low). Resolved.** `check_inline_suppressions.py`
   reports 0 violations at `e59cfa07a`.
