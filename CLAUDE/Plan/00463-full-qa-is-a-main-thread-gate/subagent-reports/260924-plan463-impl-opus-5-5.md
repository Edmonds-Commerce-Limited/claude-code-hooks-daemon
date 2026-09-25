# Plan 00463 implementation report (Opus 5.5, teammate plan463-impl)

Branch `worktree-plan-463-full-qa-gate`. The worktree is
`untracked/worktrees/worktree-plan-463-full-qa-gate/`. Phase 1 Tasks 1.2 to 1.4 are
done. Task 1.1 is done except the Workflow-tool measurement. Task 1.5 is this handover.
Phase 2 is untouched.

## What the handler does

`subagent_full_qa_blocker` (`handlers/pre_tool_use/subagent_full_qa_blocker.py`):

- PreToolUse Bash, `scope: SUB`. The chain applies it before `matches()`, so the main
  thread and synthetic probe events never reach the handler.
- HandlerID `SUBAGENT_FULL_QA_BLOCKER`, priority 32 (it runs before `enforce_llm_qa` at 41),
  terminal, RuleID `R-SUBAGENT-FULL-QA`, with guidance in `get_claude_md`.
- It is disabled by default and ships with no default patterns. The patterns are
  project-declared `full_qa_patterns` entries with these keys: `id`, `command`,
  `full_args`, `bare_is_full`, `read_only_flags` and `value_flags`.
- `targeted_qa_commands` is the RUN INSTEAD list the deny prints. With none declared, the
  deny gives generic advice to name explicit files.
- Matching works on parsed commands, never on substrings. The parser normalises line
  continuations and strips inert spans (quotes, heredoc bodies, comments). It splits on
  `&&`, `||`, `;`, `|`, newlines, subshells, backticks and a lone `&`. It then resolves
  assignments, shell keywords, command wrappers, project runners (`uv run` and similar),
  `python -m`/script and `bash -c` recursion (depth 3). It skips redirects, `--`,
  read-only flags and value flags. It normalises `./` prefixes, trailing `/` and
  absolute-path suffixes.
- A malformed config entry is reported once in the log and in `hooks-daemon check`
  (`get_enforcement_status`), and it does not match anything.
- The shared wrapper table was moved from `utils/process_probe.py` into
  `utils/shell_segmentation.py` (`COMMAND_WRAPPERS`, `peel_command_wrappers`), so both
  consumers read one table. The invariant pair and the docstrings that pointed at the old
  name were updated.

## The targeted entry point

`./scripts/qa/llm_qa.py changed` runs magic_values, format, lint, type_check, pyright,
error_hiding, project_handlers, docs_qa, plan_qa, shell_check, declared_invariant_pairs and
`changed_tests`. `changed_tests` (`scripts/qa/run_changed_tests.py`) collects the files
changed since the merge base, plus untracked files, with renames split into a deletion and
an addition. A test file selects itself. Any other file's coverage is the UNION of four
parts, since delta review N3:

- its declared rule in `scripts/qa/changed_tests_map.yaml`;
- its mirror, `tests/unit/<path>/test_<stem>*.py`;
- the tests that refer to it by path, by a path built from its parts, by a unique basename,
  or by importing it. These are read from the syntax tree, so a comment or docstring does
  not count;
- one hop of dependents' own unit tests.

A nested conftest runs its subtree. The root conftest is too broad, and so is any reach past
40 test files; a too-broad file still runs its own tests. A deleted file that a source
still refers to is unmapped. Each unmapped file carries its reason (`uncovered`,
`too-broad`, `deleted-but-referenced`), and it fails the run. `--allow-unmapped` is the
explicit escape. `--base` overrides the merge base, which defaults to origin/HEAD and
falls back to `main`. The run refuses to start on the base branch or with no changes. It
writes `untracked/qa/changed_tests.json`, and `changed_tests` is excluded from `all`.

## Review fixes (every finding except 15, which is the coordinator's review of the range)

- **M1**: an unmapped file fails the run, as described above. The two tests that pinned
  the silent pass are gone. Deleted and non-Python files are listed in the report.
- **M2**: `option_grammar: pytest` merges `PYTEST_VALUE_OPTIONS`, which covers pytest core,
  cov, xdist, timeout, randomly, rerunfailures, asyncio and html. A test pins the set
  against the installed pytest's argparse actions. Only a path-like operand narrows a run.
  An operand is path-like if it contains `/` or `::`, ends in `.py`, or exists under the
  event's `cwd`. So `pytest --cov . tests/unit/x.py` is allowed and `pytest --cov src` is
  denied.
- **M3**: `llm_qa.py` writes `untracked/qa/provenance.json`, with HEAD and a working-tree
  digest for each tool. It records "changed-during-run" when the tree moved mid-run.
  `--read-only` marks a mismatched result STALE and fails it.
- **Evasions**:
  - project runners are resolved through their own flag grammar: `uv run --frozen`,
    `uv run --`, `uvx`, `uv tool run`, poetry, pipenv, pdm and hatch;
  - attached redirects (`all>out.txt`) are split off;
  - `$PWD/` and `${PWD}/` prefixes are normalised;
  - `env -C`/`--chdir` take a value.
- **Minors**:
  - `hooks-daemon check` builds the handler through the shared `apply_handler_config`,
    so the options it reports are the ones dispatch uses. It reports a `scope` other
    than SUB.
  - The handler and evasion tests load patterns from the live YAML.
  - The flag constants are shared from `shell_segmentation`.
  - The `enforce_llm_qa` deny is role-aware.
  - The tautology test is gone.
  - QA.md warns about bare pytest.
  - The success criterion names only the two measured agent kinds.

## Delta review fixes (N1 to N10, `260924-plan463-delta-review-opus-5-5.md`)

The tests came first. Each new test was run against the code as it stood and failed before
the fix; for N3 the scenarios were also driven through HEAD's `run_changed_tests.py`, and
all six failed there.

- **N1**: each tool's provenance entry now carries the live verdict, the exit code and the
  sha256 of the report it wrote. A run deletes a tool's old report before running it.
  `--read-only` re-applies the recorded exit code, and fails a missing, replaced or unwritten
  report. `_run_tools` is tested end to end with `run_tool` stubbed: a crash with no output,
  a green report with exit 1, a replaced report, and a clean run.
- **N2**: a tree that changes during the run is printed at the end of that run. It fired for
  real during this work, when the `format` tool rewrote two files mid-run.
- **N3**: the union mapping above, with a JSON reason for each unmapped file. On this
  branch it selects 196 test files, up from 107, and it found a real defect. The new
  opt-in handler was missing from `test_default_enabled_template_consistency.py`'s expected
  set, a test the old mapping never ran. That test is now fixed. Eleven files are honestly
  `too-broad`: the constants modules, `cli.py`, `registry.py`, `handler_scope.py`,
  `init_config.py`, the handler, the dogfood config, CLAUDE.md and HOOKS-DAEMON.md.
- **N4**: each `cd` in a command moves the directory that path lookups use, and one the
  shell would expand drops back to shape. Under `option_grammar`, a flag in neither
  `PYTEST_VALUE_OPTIONS` nor the new `PYTEST_FLAG_OPTIONS` is read as taking a value, so
  it fails closed. Both sets are pinned against the installed parser. HANDLER_REFERENCE
  now says where a path-shaped value can still target a run.
- **N5**: a word after an unlisted runner flag is tried both as that flag's value and as
  the command, for the global flags and the `run` flags alike. The other fixes:
  - `uvx pytest@8` and `uv tool run pytest@8` drop the version pin;
  - `hatch run env:cmd` is split into the environment and the command;
  - `&>` splits an attached redirect;
  - `~/`, `$HOME/` and `${HOME}/` read as absolute;
  - `env -S` is off the limits list, because it is seen.
- **N6**: `tool_command` is deleted. The forwarding test now drives `run_tool`, and the
  `_run_tools` tests pin that forwarding reaches `changed_tests` only.
- **N7**: QA.md now states bare pytest as policy. Bare `pytest` from `tests/unit/core`
  collects only that directory, but the guard cannot see the shell's directory.
- **N8**: the Bugs.md FAIL-FAST cycle has the role split.
- **N9**: "never denied" and the guidance's Bash sentence are derived from `_BLOCKED_TOOLS`.
- **N10**: untracked files are hashed streamed (`hashlib.file_digest`), never read whole.

## Batched gate, lock finding and setup_worktree (00466 N2)

- **Batched integration gate** (owner's instruction; journal `decision`). The gate is
  documented in CLAUDE/QA.md under "The Batched Integration Gate":

  - every ready branch is merged `--no-ff` into ONE integration worktree from `main`;
  - `llm_qa.py all` runs once on the combined head;
  - green: `main` is fast-forwarded;
  - red: the breaking branch is bisected out, fixed or dropped, and the gate re-runs.

  AgentTeam.md, Worktree.md, IssueSdlc.md (Steps 5 and 7), PLAN.md, the handler's deny,
  `why`, guidance and docstring, HANDLER_REFERENCE, release note 13, the manifest and the
  config comment all now say the same. The AgentTeam merge procedure no longer runs the
  full suite after each child merge or again in main. `test_it_describes_the_batched_gate_not_one_run_per_branch`
  pins the deny and the guidance (RED first).

- **When main moves during a batch** (lead's refinement; journal `decision`).
  `./scripts/qa/llm_qa.py main-moved <batch-base> [<main-ref>]` classifies
  `git diff --name-only --no-renames <batch-base>..main`:

  - `unmoved` (exit 0): fast-forward;
  - `docs-only` (exit 0): merge main in, run
    `plan_qa docs_qa format british_english sensitive_content`, then fast-forward;
  - `full-gate` (exit 4): run the full gate again.

  A base that main no longer contains gives `full-gate`, and a git failure is exit 1
  with no verdict. The path set is defined once in `llm_qa.py`: a file inside a numbered
  plan folder, or a `.md` outside `src/`, `tests/` and `scripts/`. The plan directory's
  root is excluded, because `mkplan.bash` and `_planlib.inc.bash` are tested code.
  `tests/unit/qa/test_llm_qa_main_moved.py` (RED first, 56 tests) pins every boundary
  and runs against a real repository, including a rename out of `src/`. On this
  repository's own history, `830363e5..8cd131f4` (a ledger commit plus a CLAUDE.md
  regeneration) reads `docs-only`, and `94355465..830363e5` reads `full-gate`. QA.md,
  AgentTeam.md, IssueSdlc.md, Worktree.md and PLAN.md state the freeze, the verdict
  table and "CI is the second line, not a substitute".

- **Lock finding** (journal `finding`). 00463 ships no gate lock. `main-moved` is gate
  tooling, but it runs no tools and takes no lock.
  `llm_qa.py`'s own run lock is non-inheritable. `TestADaemonStartedUnderTheRunDoesNotHoldTheLock`
  pins that a daemon started during a run does not hold it after the run exits, with a
  leaking control. The `9>&-` rule for any gate lock is in CLAUDE/QA.md.

- **setup_worktree.sh** (journal `action`, ref 00466 N2). The template, the Run QA hint and
  Step 7 name `llm_qa.py` and targeted QA. `tests/unit/scripts/test_setup_worktree_qa_guidance.py`
  was RED first. Review 3 (R3) showed it judged only command-shaped lines; see below.

The `main-moved` design in the bullet above is superseded by the review 3 fixes below.

## Review 3 fixes (`260924-plan463-review3-opus-5-5.md`)

- **R1 (blocker): a hand-kept docs list let tested documents skip their tests.** The list
  is gone. `llm_qa.py main-moved` judges each moved path (`git diff --raw --no-renames`):

  - full gate: the runtime-read set, defined once as `RUNTIME_READ_FILES` (root
    `CLAUDE.md`, `CHANGELOG.md`) and `RUNTIME_READ_ROOTS` (`.claude/`, `RELEASES/`,
    `CLAUDE/UPGRADES/`); a symlink; anything that is not a `.md` outside `src/`, `tests/`
    and `scripts/`; a document the mapper reports `too-broad` or does not report;
  - otherwise the document goes through `run_changed_tests.py --range <base>..<main> --select-only`, the same mapper `changed` uses. No tests means docs; tests mean
    `targeted`.

  Verdicts and exits: `unmoved` 0, `docs-only` 5, `targeted` 6, `full-gate` 4; exit 1 is
  no verdict. `targeted` re-runs `llm_qa.py changed british_english sensitive_content --range <base>..<main>`. `TestTheReviewExamplesAgainstThisRepository` runs the real
  corpus over every path the review names: the plan README, HANDLER_DEVELOPMENT.md,
  CodeLifecycle/General.md, core/PlanWorkflow.core.md and BUG_REPORTING.md are
  `targeted`; CLAUDE.md, CHANGELOG.md, the qa-runner agent, the release skill,
  `.claude/rules/agent-docs.md`, a plan `conftest.py` and `run_me.sh` are `full-gate`.
  The root `README.md` reads `full-gate` too, because the mapper finds it `too-broad`.
  QA.md now says CI is the second line because every test that reads a moved document has
  already run in the recheck.

- **R2 (major): the batch base lived in a shell variable.** `main-moved --start` writes it
  to `refs/integration/<branch>/base`. `main-moved --advance` moves it to the merged main
  commit, only when the recheck's provenance certifies a pass on this tree (for
  `targeted`, a `changed_tests` report whose `range` is exactly `<base>..<merged>`). The
  ref is updated with an old-value check. QA.md, AgentTeam.md, IssueSdlc.md and
  Worktree.md document the loop, and what to do when `--ff-only` refuses.

- **R3: the setup_worktree test missed prose, labels, printf and single quotes.**
  Rewritten test first: every `echo`/`printf` text is judged at every place a command can
  start. Nine injected RED cases, including every row of the review's table. The 00466 N2
  paragraph is corrected on this branch; the Remedied row stays.

- **R4: `unmoved` came from an empty diff.** `unmoved` now means `main` IS the base. New
  commits that change no file (an empty commit, a commit and its revert) read
  `docs-only`, whose loop merges `main` in, so the fast-forward can succeed.

- **R5: AgentTeam.md is one model.** The parent IS the integration branch. There is no
  gate at child to parent; the gate runs once in Parent to Main STEP 1, after
  `main-moved --start`, and the ":1186" run is deleted. Children's worktrees and branches
  are kept until the batch lands, so rejects (red gate or final honesty check) go back to
  the child branch. STEP 5 and the worked example branch on `main-moved`'s exit code with
  `case`. The review suggested passing the parent as `MAIN_REF` at child to parent; with no
  gate there, the ref that must not move is `main`, so the default is right.

- **R6: a nested conftest got past the 40-file cap.** `test_file_count` weighs a directory
  entry by the test files under it, in `cover()` and `_reach()`.

- **R7: full-suite forms the blocker missed.** Now denied: `py.test`,
  `coverage run -m pytest`, `python -m` routed through the same resolver, unnormalised
  operands (`tests/./unit`), and operands resolved against a `cd`, including the start
  directory or above. Listed as limits with reasons, pinned by `TestTheDocumentedLimits` against
  HANDLER_REFERENCE.md: `$(which pytest)`, tox, nox, `hatch test`, ionice, taskset,
  xvfb-run, `script -c`, `pipx run` and ANSI-C quoting.

- **R8: a report rewritten by a later tool, or a recorded failure, read as a pass.** The
  digest is taken right after each tool runs, and `--read-only` fails a recorded
  `passed: false`.

- **R9: the undo used a denied command.** Before the push, `git reset --keep` to the base
  ref (allowed; only `--hard` is denied). After a push: fix forward, or `git revert -m 1`
  with the revert-the-revert caveat. Dropping a branch builds a new integration branch;
  never `revert -m 1` to drop.

- **R10: the docs recheck list.** `format` (black, Python-only, auto-fixing) is out of
  `DOCS_ONLY_TOOL_NAMES`. The test asserts the list is a subset of `TOOL_REGISTRY` and that
  the command prints it, not the literal list. QA.md says a `docs-only` or `targeted`
  landing leaves other tools STALE, so a release still needs its own full run.

- **R11: argument position and a shared exit code.** `--read-only` is stripped before
  `main-moved` is dispatched, and `main-moved` anywhere but first is an error naming the
  right form. Each verdict has its own exit code.

- **N3 and N4 (partial in review 3):** closed by R6 (directory weighing) and R7 (operand
  normalisation and `cd` resolution).

- **R12 and R13:** symlinks (mode `120000`) and non-documents read `full-gate`, so a plan
  folder no longer admits any file type. The orchestrator-simulate record says "recorded, not a would-be denial
  (the call names no tool)" for a call with no `tool_name`; PLAN.md's long line is
  rewrapped.

## Review 4 fixes (`260924-plan463-review4-opus-5-5.md`)

Every reproduction became a RED test first. Commits: `ba513f23` (N1, N2, N12),
`49b4e3dc` (the blocker), `091a3ee3` (N3, N7, N11 and the docs), `403e3284` (merge of
main at `57a255cb`).

- **N1 (major): documents read by glob.** `changed_tests_map.yaml` gains a `path_glob`
  key (Path.glob semantics: `*` within a segment, `**` at any depth), and every matching
  rule now applies, not the first. Declared: the documented-commands checker, the
  branch-install gate, the skill-reference and skill-surface tests, and the repo-hygiene
  fixtures. Tests: `tests/unit/qa/test_run_changed_tests.py` (malformed rules,
  `path_glob` semantics, union of rules);
  `tests/unit/qa/test_glob_readers_are_declared.py`, whose `TestEveryGlobReaderIsDeclared`
  scans `tests/` with the AST for `.glob`/`.rglob`/`os.walk` over the repo and fails on an
  undeclared reader, and whose `TestTheReviewReproduction` pins the review's pages as
  `targeted`. QA.md says how glob readers are declared, and which checkers run in the
  recheck.

- **N2 (major): the head that lands.** `refs/integration/certified/<branch>` is written
  only by a passing `all` over every tool on a clean tree (`_certify_gate`) or a
  successful `--advance`. `main-moved` says `head-moved` (exit 7) first, unless HEAD is
  that head on a clean tree. `--advance` refuses a dirty tree, needs a certified head,
  and refuses any commit since it that is not a merge, and any merge that edits a path
  `main` did not move (compared against `git merge-tree`'s automatic merge). `--start`
  refuses a second start without `--restart`, which clears the certified head. The
  review's reproductions: (a) `TestTheCertifiedHead`, (b)
  `TestAdvancingNeedsTheHeadThatLands`, (c) `TestStartingTwice`, all in
  `tests/unit/qa/test_llm_qa_main_moved.py`, with `TestTheGateRunCertifies` and
  `TestFinishing`.

- **N3: `case $?` under `set -e`.** Both AgentTeam.md blocks use
  `rc=0; ./scripts/qa/llm_qa.py main-moved || rc=$?; case $rc in … esac`, with a
  `head-moved` branch. `tests/integration/test_main_moved_branching_survives_errexit.py`
  takes both snippets from the document and EXECUTES them under `set -euo pipefail`
  for exits 0, 1, 4, 5, 6 and 7, with `llm_qa.py` and `git` stubbed: every run reaches
  the end, and only exit 0 fast-forwards.

- **N4-N6, N8, N9 (blocker).** In `test_subagent_full_qa_blocker.py` (`_FULL_RUNS`,
  `_NOT_FULL_RUNS`, `TestWhatCannotBeParsed`, `TestTheParserEdges`,
  `TestTheDirectoryTheCommandCdsInto`, `TestOperandsAreJudgedFromTheirRepository`):

  - N4: `$(…)` and backticks inside double quotes are followed;

  - N5: globs and braces are judged by what they reach; `eval`, `bash <<<`,
    echo/printf piped into a shell, `bash < <(echo …)`, `source`/`.`, `time -p` and
    `builtin` are followed; `$'…'` is decoded locally, not through 464's lexer;

  - N6: operands are resolved and judged against the nearest `.git`/`pyproject.toml`;

  - N8: `.` after a `cd` resolves where the cd went, and a BARE run after a cd is judged
    as `.` from there, so `cd tests/unit/qa && pytest -q` is targeted;

  - N9: `xargs` runs its command, judged by its explicit arguments;

  - the reviewer's probe list beyond that: `$(pwd)/tests`, `setsid`, `ionice`, `chrt`,
    `taskset`, `flock` (and `flock -c`), `xvfb-run`, `script -c`, `parallel … ::: …` and
    `pipx run` are now followed;

  - the lead's rule: an unparseable command naming a declared program is DENIED, with
    "UNPARSED: this command could not be parsed" in the reason.

  - after the lead's follow-up: a literal `python -c` string (any interpreter, a venv
    `bin/python`, or through `uv run`) that mentions `pytest` is judged as a pytest run.
    It is a substring test on the literal, and the string's quoted literals are the
    run's words, so `pytest.main()` and `pytest.main(["tests"])` are full and
    `pytest.main(["tests/unit/qa/test_x.py"])` is targeted. A `"-m"` just before a
    `"pytest"` literal is dropped as the module selector. Tests:
    `TestPythonCodeThatRunsPytest`, which also re-checks `python -m pytest`.

  The reviewer's `probe_463r4_blocker.py` now reports 0 mismatches of 166. The
  remaining documented limits are `$(which pytest)`, `"$(command -v pytest)"`,
  `hatch test`, tox, nox, `cat commands.txt | bash` and `bash < commands.txt`, each
  pinned in `_DOCUMENTED_LIMITS` against HANDLER_REFERENCE.md. The blocker module's line
  coverage from its tests is 98.8%.

- **N7: prose that avoids the start words.** The guidance test now starts a candidate at
  any word naming a declared program, reads `cat` heredoc bodies, and expands `NAME=value`
  assignments. Ten new RED rows (the probe's six plus `<<-` and `${NAME}` forms), and a
  negative set (a narrow pytest, a `python3 <<'PY'` body, `llm_qa.py changed`). The
  reviewer's `probe_463r4_setup_worktree.py` catches all nine rows. Widening it flagged
  three of the script's own lines that mentioned pytest bare. They are reworded, and the
  agent template now names a path: `pytest tests/unit/qa/test_x.py`.

- **N10: a quoted heredoc delimiter holding a blank.** The shared
  `utils/shell_segmentation.py` delimiter pattern accepts it;
  `test_a_quoted_delimiter_holding_a_blank_is_inert`. This is a change to a shared
  module, so it affects every handler that blanks heredoc bodies.

- **N11.** AgentTeam.md deletes the parent with `git branch -d` (it was fast-forwarded
  into main). Dropping a child builds a new parent from `main`, and QA.md says the new
  branch becomes the plan's parent.

- **N12.** The refs are kind-first (`refs/integration/base/<branch>`,
  `refs/integration/certified/<branch>`), which mirrors the branch namespace, so two refs
  cannot collide. `--finish` deletes both once `main` holds the certified head. The
  targeted range check compares resolved commits.

**Merge of main (`57a255cb`).** Conflicts:

- `llm_qa.py`: both sides are kept. Main's `ensure_live_daemon` now runs inside this
  branch's provenance-recording run.
- Main's `test_llm_qa_live_daemon.py` fixture now:
  - stubs `run_tool` and `summarize_tool` with this branch's signatures;
  - points `QA_OUTPUT_DIR` at a temporary directory. Without that, its live run would
    delete and rewrite the checkout's real `untracked/qa/` reports.
- CLAUDE.md and HOOKS-DAEMON.md are regenerated.
- 00466 PLAN.md and NIGGLES.md: main's rows are kept, with N2 set to Remedied.

The 00466 journal needed a different fix. This branch's 18:36 N2 correction landed before
main's 17:50 and 18:24 entries. `plan_journal_guard` refuses a hand-moved entry, so the
entry was deleted from that position and re-appended through `mkplan.bash` at the
current time. The file is in time order, and nothing else in it changed.

Main's release notes run to 20, so this plan's note is now `21-…md`.

**Also changed:** ledger 00466 N29 records "return a local assigned in the handler" as
evading `error_hiding`, and this branch had just done that in the blocker's `_words`.
That code is reshaped: the shlex failure is caught where the unparsed verdict is
produced, and no None-returning helper remains.

## Review 5 fixes (`260924-plan463-review5-opus-5-5.md`)

Every finding is fixed, none deferred, each with the reviewer's probe as a RED test
first. The reviewer's corpus (`probe_463v5_blocker.py`, 266 rows) now gives 0 false
denies and 0 false allows (it gave 6 and 17), and its 12 extra `cd` rows all match
their expectation.

**Majors (`39d56b24`).**

- **M1.** A `full_args` entry with no `/` (`all`, `tests`) is matched literally BEFORE
  path resolution, unless something of that name exists where the command stands.
  `TestSubcommandWordsAfterACd` holds the reviewer's 9 `cd` rows, a read-only control and
  the `tests`-exists-here case.
- **M2.** Brace expansion is a lazy generator cut by `islice` at the cap, with a limit
  on the number of groups. Past either limit the word fails closed.
  `TestBraceExpansionIsBounded` holds 24, 40 and 200 groups each under 1 s, and 2000
  nested braces.

**The 17 false allows, and what each became.** Each "documented limit" is either FIXED
(read and judged) or FAILS CLOSED (denied, with a `JUDGED UNSEEN` line saying why):

| Row(s)                                                   | Now                                                                                              |
| -------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| `env --`, `nice --`, `timeout -- 600`                    | Fixed in the shared `peel_command_wrappers`, which skips `--` for every guard                    |
| `script -qc`                                             | Fixed: a code flag's letter is found inside a short cluster                                      |
| `exec -a qa`, `/usr/bin/time -v`, `strace`, `caffeinate` | Fixed: launchers with their own grammars (also `ltrace`, `doas`)                                 |
| `$'py\x74est'`, `$'py\164est'`                           | Fixed: `\x`, octal, `\u` and `\U` are decoded                                                    |
| `function t { pytest; }; t`                              | Fixed: the `function` keyword and name are skipped like `t()`                                    |
| `P=pytest; $P tests`, `QA=...; $QA all`                  | Fixed: variables the command sets (and `for` loop values) are expanded                           |
| Python heredoc (two rows)                                | Fixed: heredoc, here-string, pipe and file code for Python go through the same judgement as `-c` |
| M1's `cd scripts/qa && ./llm_qa.py all`                  | Fixed (M1)                                                                                       |
| `$(which pytest)`, `"$(command -v pytest)" tests`        | Fail closed: judged as each declared program the substitution names                              |
| an unset `$VAR` in command position                      | Fail closed: judged as each declared program the whole command names                             |
| `cat commands.txt \| bash`, `bash < commands.txt`        | Fixed: a regular file up to 64 KiB is read and judged; otherwise judged by its name              |
| `hatch test`                                             | Fixed: hatch's pytest, its own options dropped                                                   |
| `tox`, `nox`                                             | The declaration model: a project declares them (`TestARunnerTheProjectDeclares`)                 |
| `__import__('py'+'test').main()` (obfuscation)           | Fail closed: a module imported or run by a computed name, or a computed `exec`/`eval`            |

An unquoted `$(...)` or backtick span is kept as one word while the command is split, so
a substitution in command position is no longer lost to the `(` boundary. Its code is
still judged one level down. Nesting past three levels, and more than 32 launcher hops,
now fail closed (n6) instead of being skipped or raising `RecursionError`.

**The 6 false denies.**

- Three import and version probes (m1): Python code is a run only when it CALLS pytest
  (`pytest.main(`, `from pytest import main` then `main(`, a `"pytest"` literal in a
  process call, or an import of the literal module). The words after `-c` code that
  reads `sys.argv` are the run's operands.
- `env -C tests/unit/qa pytest` (n3): `env -C`/`--chdir` is a `cd` for that one command,
  pushed and popped, so a later command is judged from where it started.
- `pytest $(git diff --name-only …)` and `git diff --name-only … | xargs pytest` (n3): a
  `git diff|show|log --name-only` listing, optionally through `grep`/`sort`/`uniq`, is a
  targeted run.

Any OTHER operand built at run time (`$(cat more.txt)`, `"$EXTRA"`) now fails closed. The
handler reference lists those false denies, and `echo tests | xargs pytest`, as the price
of that rule.

**Minors.**

- **m4.** The guard also compares each reader's literal root-relative markdown globs with
  the rules naming it (the reviewer's `CLAUDE/Architecture/*.md` reproduction is
  `TestEveryPatternOfAReaderIsDeclared`). The scanner now sees `.iterdir()`,
  `os.listdir`/`scandir`, `glob.glob`/`iglob` and a `git ls-files` run on the repository,
  in a test that reads markdown. It found no new undeclared reader; one false positive
  (a `git ls-files` in a `tmp_path` repository) is pinned as not a reader.
- **m5.** `unmoved` prints `git merge --ff-only <certified sha>`, and both AgentTeam.md
  fences merge `$(git rev-parse refs/integration/certified/<branch>)`. `--finish`
  accepts only `main` equal to the certified head, or a merge with it as a parent and
  the same tree; a descendant is refused and the refs stay.
- **m6.** When `main` is already merged into the certified head and the verdict's
  recheck already passed on the tree, `main-moved` prints only `--advance` and the
  recheck.
- **m7.** The shared heredoc opener has a `(?<!<)` lookbehind, so the lines after
  `cat <<<'X'` are judged.

**Nits.** n1: each non-zero fence branch exits with the verdict, and the errexit test
checks the exit code, the branch message and that nothing after it ran. n2: `unmoved`
needs HEAD to contain `main`; otherwise `head-moved`, with a printed "merge main back
in" step. n3 and n4: documented and fixed as above. n5: a command over 32 KiB is not
parsed; it is denied only when it names a declared program. The cap is on the raw text,
because blanking heredoc bodies is itself quadratic in unclosed openers (10,000 of them
took 7 s). n7: QA.md records that a file created and deleted during a run still
certifies. n8: the guidance test's docstring states its conservative flag.

**Verification of this round.** The reviewer's timing probe: its slowest row is now
0.13 s (it was 18 s for braces, 36 s for 1 MB). Its S9c, S12 and S13 scenarios are unit
tests in `test_llm_qa_main_moved.py` (`TestExactlyTheCertifiedHeadLands`,
`TestTheGateIsNotRunTwiceOnOneHead`); the clone-based `probe_463v5_n2b.sh` was not
re-run, as its clone holds the old code.

## Review 6 fixes (`260924-plan463-review6-opus-5-5.md`)

The review was committed first (`53f646f8`). Every finding except n6 (not this
teammate's) is fixed, each with a RED test first. No exclusion, suppression or
`nosec` was added.

**Majors.**

- **M1.** One `_Event` carries the per-event state: a memo of each path read (read at
  most once), one 32 KiB parse budget over all file content, and a 16 MiB scan budget.
  Past the parse budget a file is only scanned for a declared program's name, and a hit
  fails closed with `JUDGED UNSEEN`. A substring pre-check and a per-path cache keep the
  scan linear. `TestTheCodeFileReaderIsBounded` pins the fanout fixture and 80 feeds of
  `cat plain64k | bash`, each under 1 s (both about 0.03 s in the reviewer's filebomb
  probe now).
- **M2.** A `| xargs pytest` consumer of a listing is targeted only with `-r` or
  `--no-run-if-empty`, and a `$(listing)` only beside a literal target. A listing steered
  to print other words (`--format`, `--pretty`, `--line-prefix`, `--output`,
  `--no-index`, the empty tree, a word built at run time, `grep --label`) is none, and
  `git log`/`git show` are no longer listings (they print commit messages). The handler
  reference shows `xargs -r`.

**Minors.**

- **m1.** `full_words` (always literal, never a path) is new; `full_args` are paths and
  keep the existence check. The live `llm-qa-whole-suite` pattern declares
  `full_words: [all, tests]`.
- **m2.** Code on stdin is read only from `echo`, `printf` (formatted) and a
  single-operand `cat FILE`. Any other producer, another descriptor, a FIFO or device, a
  path the same command writes, or a file past the scan budget is `JUDGED UNSEEN`.
  `/dev/stdin`, `/dev/fd/0`, `-` and `<(...)` are stdin. `bash -c "$(cat f)"` and
  `eval "$(cat f)"` READ `f` (a design choice: seen, not denied). A script run by name or
  path is read too, judged with its own `"$@"`/`$1`/`${1:-x}`.
- **m3.** Python's short flags and the shared peel's wrapper value flags are read letter
  by letter (`-Ic`, `-Bm`, `env -iu HOME`, `nice -n5`). `import pytest as p`,
  `from pytest import main as m` and `_pytest` are calls. `env -` is `env -i`. The
  shared-peel change is `CommandWrapper.lone_dash_is_flag` plus `_takes_next_word`, with
  tests in `test_shell_segmentation.py`.
- **m4.** `PYTEST_ADDOPTS` words, inline and exported, are pytest's own; an `@file`
  operand is full (unseen).
- **m5.** The glob-reader guard resolves a receiver joined or held in a constant,
  f-strings, concatenation, `Path.walk`, aliases, a git argv in a variable or split from
  a string, and roots from `getcwd`, `rootpath` and `parents[N]`.
- **m6.** `value_flags: [--range]`; an opaque word with `-c`/`-m` is an interpreter;
  brackets after `::` are no glob; `pushd`/`popd` are followed as a stack.
- **m7.** Brace sequences (`{t..t}ests`, `{1..3}`); `${NAME:-word}`/`${NAME:=word}` read
  as `word` when NAME is unset.
- **m8.** A clean head holding nothing past the certified head but `main` merged in
  gets the main-moved verdict with its recheck, not `head-moved`, by the same rule
  `--advance` applies (`_work_beside_main`, shared by both).

**Nits.** n1: an `OSError` in `_repository_root` reads as no marker (it now goes through
`utils.path_predicates.path_exists`, which also clears `check_eacces_safe_predicates`).
n2: every fail-closed deny carries `JUDGED UNSEEN`; the brace cap (64 alternatives, 32
groups; past it a group reads as `*`, and an alternative holding `/` fails closed) is in
the handler reference. n3: `_merges_exactly` is TIGHTENED to match its text: exactly two
parents, one the certified head, the other an ancestor of it, and the same tree
(same-tree child, unrelated and octopus merges are refused, pinned in
`TestExactlyTheCertifiedHeadLands`). n4: `timeout 60 -- x` runs `--`. n5: `coproc`,
`alias` under `expand_aliases`, `hash -p` and nested `env -C` are followed. n7: the
handler reference advises the narrower spelling (`tests/unit/qa/test_llm_qa*.py`).

**Corpus.** `probe_463v6_blocker.py`, 279 rows: 0 false denies, 2 false allows, both the
one accepted limit, a program NAME built at run time from pieces
(`P=$(printf 'py%s' test); $P tests`, `s.call(["py" + "test"])`). 4 documented denies
(`tests/unit/**/test_llm_qa*.py`, `$(ls ...)`, `find | xargs pytest`, `"$EXTRA"`).
Slowest row 0.11 s. `probe_463v5_blocker.py` (266 rows): 0 false allows; its 2 "false
denies" are its old expectations for a bare `| xargs pytest` and a lone `$(git diff)`,
which M2 makes denies by design. Its 12 `cd` rows all match.

**Design choices worth a second look.**

- Under `option_grammar`, every positional word is a target (pytest stops on a missing
  path), so `cd tests/unit && pytest tests` is targeted.
- A `--pyargs` module not found under the cwd is unseen.
- Any stdin producer not understood denies unconditionally, so a script running
  `eval "$(ssh-agent -s)"` beside a declared program would be denied.
  `scripts/install/prerequisites.sh` (it pipes a download into `sh`) fails closed for
  this reason, pinned in the repo-scripts test.

**Two gate false positives met on the way.**

- `secret_file_guard` denied an `Edit` whose code held the token `*words[1:]]`; the
  line was rewritten as `renames[words[0]] + words[1:]`. Not fixed here: reported to the
  coordinator for the niggles ledger.
- `audit_error_hiding` flagged a generator's bare `return` after it had YIELDED the
  deny as `return-none-on-error`. Fixed in the detector with RED tests
  (`TestAGeneratorThatYieldsTheFailure`): a handler that yields before its bare `return`
  has reported the failure; one that stops without yielding is still flagged.

**Verification.** Targeted only: `format lint type_check pyright magic_values error_hiding`, `docs_qa plan_qa british_english sensitive_content repo_hygiene doc_truth doc_snippets handler_reference shell_check`, every `scripts/qa/check_*.py` Detector, and
pytest on the touched and related files (the blocker, shell segmentation, all of
`tests/unit/qa/`, the pipe_blocker family, process probe, the deadlock integration test,
documented commands, handler reference, invariant pairs), all green.

## Task 1.1 measurements

- **In-process teammate: `agent_id` is present.** Measured live on this teammate's own
  payload: `agent_id` was 30 characters, `agent_type` was `plan463-impl`. The journal
  records it as a finding with ref T1.1.
- **Agent-tool sub-agent: `agent_id` is present.** The evidence is from Plans 00418 and
  00423 (17 characters).
- **Workflow-tool agent: UNMEASURED.** The probe needs the owner's explicit opt-in to the
  Workflow tool, and the lead has asked the owner for it. The handler's docstring and
  guidance, HANDLER_REFERENCE.md, CLAUDE/QA.md and release note 13 claim coverage only for
  Agent-tool sub-agents and teammates. Admission keys only on a non-empty `agent_id`, so
  nothing changes if Workflow agents turn out to carry it. A parametrised scope test pins
  this: ids of 17, 30 and 1 characters are admitted, and an empty id is not. The
  `handler_scope.py` docstring records the 30-character teammate measurement. Task 1.1 is
  ticked with the Workflow point recorded as unmeasured.
- **Default:** disabled, with empty patterns. Client QA commands vary, so a default
  populated from this repo's commands would never fire in a client project.
- **Orchestrator-only mode (00418): no deadlock, now proven on the real chain.** The
  first version of this report said "no deadlock", and that stands; the coordinator's
  reviewer confirmed it against the real handler. The only test pinning it ran the
  handler on its own, though. Meanwhile, on every main-thread Bash call, the simulate
  record said "main thread would have been denied — Bash: ...", which looked like
  contrary evidence.
  - **Cause.** `orchestrator_simulate.py` `handle()` printed that text for every call
    `matches()` flags. The blocking policy (`_would_deny`) refuses only Write, Edit and
    NotebookEdit outside `CLAUDE/Plan/`. The record was false; the policy was not.
  - **Fixed here; this remedies ledger 00422 N24.** The fix was committed at `14c0b806`,
    reverted at `f330cf41` on an earlier direction, and restored once the coordinator
    accepted it as the N24 remedy. `_policy_denies()` holds the policy, and `_would_deny()`
    gates it on the switch. The simulate record says "would have been denied" only when
    that policy denies. Other matched calls read "recorded, not a would-be denial", and
    Bash adds "Bash is never denied by this mode". `TestTheSimulatedRecordTellsTheTruth`
    ties the record to the armed verdict across the tool surface. The integration test
    checks that the full gate's record carries no would-be denial. The coordinator ticks
    N24 when 00463 merges.
  - **The real policy against the real gate (kept).**
    `tests/integration/test_full_qa_gate_is_never_deadlocked.py` builds the live PreToolUse
    chain: library handlers via `register_all()` on this repo's config, plus all discovered
    project handlers, with orchestrator-simulate ARMED. The main thread's
    `./scripts/qa/llm_qa.py all` gets ALLOW, both from the chain and from the orchestrator.
    Two controls show the chain is armed: a main-thread Edit is denied
    (R-ORCHESTRATOR-MAIN-THREAD-WRITE), and a sub-agent's `llm_qa.py all` is denied by
    subagent-full-qa-blocker.
  - **No allowlist entry.** Bash is outside the policy's blocked-tool set, so an entry for
    `llm_qa.py all` would never run. The integration test is the explicit pin, and it fails
    first if the policy ever gains a Bash branch.

## Configuration and docs

- `.claude/hooks-daemon.yaml` enables the handler with these patterns:
  - `llm_qa.py` with `all` or `tests`;
  - `run_all.sh`;
  - `run_tests.sh`;
  - `validate_worktrees.sh`;
  - whole-suite pytest: bare, `tests`, `tests/unit` or `.`.
- The `.example` file and the `init_config` template carry a disabled entry.
- The release note is `UNRELEASED/release-notes/21-...md` (renumbered from 13 at the
  merge of main). The config-changes manifest
  is `UNRELEASED/config-changes/v3.67.0.yaml`. That filename may collide with other
  in-flight plans' manifests at merge.
- Docs:
  - CLAUDE/QA.md has the canonical section "Full QA Is the Coordinator's Gate; Sub-Agents
    Run Targeted QA".
  - AgentTeam.md, IssueSdlc.md and Worktree.md carry the split.
  - CodeLifecycle General, Features and Bugs point to QA.md.
  - docs/guides/HANDLER_REFERENCE.md has the new handler.
  - The agent definitions (qa-runner, qa-fixer, release-agent) never run the full suite.
- `.claude/HOOKS-DAEMON.md` and CLAUDE.md were regenerated. The daemon auto-committed
  the CLAUDE.md block on this branch (`9a7a5ac2`). On main it regenerates on the first
  restart after merge, so a conflict there resolves by taking either side and restarting.

## Verification (targeted only, under this plan's rule)

- After the review 5 fixes: format, lint, type_check, pyright, magic_values,
  error_hiding, docs_qa, plan_qa, british_english, sensitive_content, repo_hygiene,
  doc_truth, doc_snippets and handler_reference all passed. A targeted pytest run passed
  2545, with 1 skipped and 1 xfailed. It covered the blocker, shell segmentation and
  every handler using the shared helpers, `tests/unit/qa/test_llm_qa_*`, the glob-reader
  guard, the mapper, the errexit, documented-commands, deadlock and dogfood-config
  integration tests, and the setup_worktree guidance test.

- After the review 4 fixes, before the merge: `./scripts/qa/llm_qa.py changed --allow-unmapped` passed 12/12, with `changed_tests` at 7550 passed, 12 skipped, from
  207 test files mapped from 68 changed files (11 unmapped, all `too-broad`). Named
  tools passed: format, lint, type_check, pyright, magic_values, error_hiding,
  shell_check, docs_qa, plan_qa, british_english, sensitive_content, handler_reference,
  doc_truth, doc_snippets, repo_hygiene.

- After the merge of main: the same static tools plus `generated_doc_drift` passed. A
  targeted pytest run passed 2101, with 1 skipped. It covered:

  - `tests/unit/qa`;
  - the blocker, evasion and shell-segmentation tests;
  - the setup_worktree test;
  - the errexit, deadlock, documented-commands, doc-truth, guidance-coverage and
    repo-hygiene integration tests.

- The worktree daemon was restarted and reported RUNNING before each commit.

Review 3 round:

- After the review 3 fixes: `./scripts/qa/llm_qa.py changed --allow-unmapped` passed
  12/12, with `changed_tests` at 7316 passed, 12 skipped, from 204 test files mapped from
  66 changed files. The 11 unmapped files are `too-broad` and the full gate's. The named
  tools (format, lint, type_check, pyright, magic_values, error_hiding, docs_qa, plan_qa,
  handler_reference, british_english, shell_check, declared_invariant_pairs,
  sensitive_content, project_handlers) passed; black reformatted five of the changed
  Python files first. `tests/unit/qa`, the setup_worktree test, the blocker and evasion
  tests, the orchestrator-simulate tests and the deadlock integration test: 1377 passed.
  The guidance-coverage, documented-commands, handler-reference and doc-truth
  integration tests: 337 passed.

Earlier rounds:

- After the delta review fixes, `./scripts/qa/llm_qa.py changed --allow-unmapped` passed
  12/12. That was 6979 tests from 196 test files, mapped from 59 changed files. The 11
  unmapped files are the too-broad ones listed above, and they are the full gate's. Without
  `--allow-unmapped` the run fails on exactly those 11. A further targeted run of the QA
  scripts, handler, evasion, shell utility, CLI status, registry, deadlock and doc/config
  integration tests passed 2100.
- docs_qa, plan_qa, doc_truth, repo_hygiene, british_english, handler_reference,
  declared_invariant_pairs and security were clean.
- The broader targeted pytest runs all passed:
  - `tests/unit/handlers/pre_tool_use`, `tests/unit/core`, `tests/unit/config` and
    `tests/config`: 6561 passed, 2 xfailed (the xfails were there before this work);
  - the integration wiring suites and guidance coverage;
  - the doc and command integration tests: 236 passed.
- Live probes through `.claude/hooks/pre-tool-use` against this worktree's daemon:
  - a sub-agent's `llm_qa.py all` was DENIED with the full reason;
  - a sub-agent's `llm_qa.py changed` was allowed;
  - the main thread's `llm_qa.py all` was allowed;
  - a synthetic sub-agent event was allowed.

## For the coordinator

- A niggle for the open ledger, not filed from this branch: `pipe_blocker` denied
  `grep -n "a\|--finish\|head-moved\|^#" CLAUDE/QA.md | bin/echd-capture --head 80` as
  R-PIPE-TO-HEAD. It split at `\|` inside the double-quoted pattern, then read the stage
  starting `head-moved` as `head`. The 00463 journal has the finding.

- Review 5 n9, for the open ledger and not filed from this branch: an UNESCAPED `|`
  inside double quotes also trips `pipe_blocker` (`grep -n -E "exit (code )?[0-9]|head-moved"`),
  which widens 00466 N32; a `grep` for the literal text of a force branch-delete was
  denied as R-GIT-BRANCH-FORCE-DELETE; and a redirect to `../x.txt` after a `cd` into a
  clone was denied as outside the project (00466 N28).

- Put this branch through the batched integration gate with the other ready branches
  (Task 2.1).

- The Workflow-tool probe is the only open measurement.
