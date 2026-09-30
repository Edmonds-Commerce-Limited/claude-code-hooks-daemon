# Quality Assurance Pipeline

**Version**: 1.0
**Status**: Primary source of truth for QA workflow
**Audience**: All developers and AI agents

> **Run every command below from the PROJECT ROOT.** Paths like
> `./bin/hooks-daemon` and `./scripts/qa/...` are relative to it, and resolve to
> nothing from anywhere else (`exit 127`).

---

## Overview

Complete quality assurance for the Claude Code Hooks Daemon consists of **three layers**:

1. **Automated QA** (`./scripts/qa/llm_qa.py all`) - Fast, deterministic checks
2. **Sub-Agent QA** (via Task tool) - Deep architectural review and value verification
3. **Acceptance Testing** (Agentic) - Real-world scenario validation performed by AI agents before release

**CRITICAL**: All three layers are required for production-ready code. Each layer catches different types of issues.

---

## Automated QA (Layer 1)

### Running Automated QA

```bash
./scripts/qa/llm_qa.py all       # the FULL gate: the coordinator (main thread) runs this
./scripts/qa/llm_qa.py changed   # TARGETED: what a sub-agent runs before handing over
./scripts/qa/llm_qa.py main-moved  # the coordinator: what must re-run if main moved
```

Agents MUST use `llm_qa.py`, never `run_all.sh`: the `enforce_llm_qa` project
handler denies a direct `run_all.sh` invocation by an agent. `run_all.sh` remains
the human-at-a-terminal entry point and runs the same suite with verbose output.

### Full QA Is the Coordinator's Gate; Sub-Agents Run Targeted QA

The full suite runs **once per batch, on the coordinator's thread**: every
ready branch is merged into one integration worktree, and one run covers them
all. A sub-agent never runs it. This is enforced: in a sub-agent,
`subagent_full_qa_blocker` (Plan 00463) denies every command this repository
declares as full, which is `llm_qa.py all`, `llm_qa.py tests`, `run_all.sh`,
`run_tests.sh`, `scripts/validate_worktrees.sh`, and a `pytest` with no path
(run from the repository root) or with `tests/`, `tests/unit` or the root as
its path. The deny lists the targeted
forms. The main thread is never affected.

**Which sub-agents the deny reaches.** The guard recognises a sub-agent by the
`agent_id` field in its hook payload. That field is proven present for
Agent-tool sub-agents (Plan 00423) and in-process teammates (Plan 00463). A
Workflow-tool agent's payload is UNMEASURED, so no deny is promised there. The
split below applies to every kind of sub-agent all the same.

**Why.** When the rule was made, five full runs were executing at once, one
per worktree, each about 25,700 tests over 15-20 minutes on eight cores. Each
agent re-ran the suite after every fix round, and the coordinator ran it again
before merging. The per-checkout run lock (Plan 00262) cannot help across
worktrees. A coordinator gate that still ran once per branch, one at a time,
only moved the queue: N ready branches cost N full runs, N pushes and N CI runs.

**Why the gate stays BEFORE `main` moves.** Cross-cutting checks break from
changes far away: guidance coverage, docs QA, plan QA, the handler reference and
the acceptance probes. A first full run on `main` would land every such break
there, and merges queued behind it would build on a red tree. The integration
worktree is where those breaks surface instead, including the ones that only
exist when two branches meet.

### The Batched Integration Gate

The coordinator, never a sub-agent:

1. Creates ONE integration branch and worktree from current `main`. In an
   agent team the plan's parent branch IS the integration branch, with `main`
   merged into it ([AgentTeam.md](AgentTeam.md), "Parent → Main").
2. Merges every ready branch into it, each with `git merge --no-ff`, so each
   branch lands as one merge commit and `git branch -d` still works.
3. Records the **batch base** with `./scripts/qa/llm_qa.py main-moved --start`,
   run on the integration branch. The base is the newest `main` commit the
   branch contains, kept in the git ref `refs/integration/base/<branch>`, so it
   survives between shell calls (a shell variable does not). A second `--start`
   refuses while a base is recorded, because it would move the base past
   whatever `main` added since. Only a batch rebuilt from scratch takes
   `--start --restart`, which also clears the certified head below.
4. Runs `./scripts/qa/llm_qa.py all` once, on the combined head, on a clean
   tree. A run in which every tool passes records that head as the
   **certified head**, in `refs/integration/certified/<branch>`. Nothing else
   writes it except a successful `--advance`. The tree is compared before and
   after the run, so an edit that is still there fails the certification. A
   file created and deleted again DURING the run leaves the two equal, and is
   not caught: that is a limit of comparing states.
5. **Green:** runs `./scripts/qa/llm_qa.py main-moved` and follows its verdict
   (below) until it says `unmoved`. Then, from the main checkout,
   `git merge --ff-only <certified sha>`, restarts the daemon, and pushes. The
   sha is the one `unmoved` prints, or
   `$(git rev-parse refs/integration/certified/<branch>)`. Never merge the
   branch NAME: a commit that reached the branch after the check was never
   gated. One push, one CI run. Last, `./scripts/qa/llm_qa.py main-moved --finish` in the integration worktree deletes both batch refs. It refuses
   unless `main` IS the certified head, or a merge of it with the certified
   tree. A descendant carrying anything more is refused, and the refs stay as
   the evidence.
6. **Red:** see "A red batch" below.

**The coordinator's `llm_qa.py all` (step 4) is the only run holding the
host-wide full-QA lock.** A sub-agent's `subagent_full_qa_blocker` handler is
the friendly first line, but a Bash-text denylist can never enumerate every
way to start a whole-suite run. So `tests/conftest.py`
(`claude_code_hooks_daemon.qa.full_qa_gate`) refuses a whole-suite-sized
pytest COLLECTION outright unless it holds that lock, proven by an inherited
file descriptor on the lock file -- the sink every route ends up at,
regardless of what launched it. `scripts/qa/run_tests.sh` and CI both acquire
it before their own whole-suite pytest run; see
`src/claude_code_hooks_daemon/qa/full_qa_lock.py` and Plan
00463's "Round 9" note for the design.

**While a batch is in flight, `main` is frozen for code.** The coordinator's
own doc commits (ledger rows, journal entries, archival) either wait for the
batch to land, or are committed onto the integration branch BEFORE step 4. A
commit after the certified head makes the verdict `head-moved`, and
`llm_qa.py all` must pass again.

**If `main` moves anyway, a checked verdict decides, not a judgement.**
`llm_qa.py main-moved [<main-ref>]` judges every path that
`git diff --no-renames <base> <main>` changed. A rename counts by both of its
paths, so a file moved out of `src/` is judged by the path it left.

- **Full gate:** a path runtime code reads (root `CLAUDE.md`, `CHANGELOG.md`,
  `.claude/**`, `RELEASES/**`, `CLAUDE/UPGRADES/**`), a symlink, anything that
  is not a `.md` file outside `src/`, `tests/` and `scripts/`, and a document
  the test mapper cannot target (`too-broad`, as the root `README.md` is).
- **Tested:** a document the test mapper maps to tests. The mapper is
  `run_changed_tests.py`, the one `llm_qa.py changed` runs, never a second copy.
  It finds the tests that name the file, its declared rules and its dependents.
  A test that finds documents by globbing a directory never names the file, so
  it is declared in `scripts/qa/changed_tests_map.yaml` with a `path_glob`
  rule, and `tests/unit/qa/test_glob_readers_are_declared.py` fails while such
  a test is undeclared, or while a literal glob it writes from the repository
  root (a `DOCUMENT_GLOBS` entry) matches a path no rule naming it covers. The
  guard sees `.glob`/`.rglob`, `os.walk`, and, in a test that reads markdown,
  `.iterdir()`, `os.listdir`/`os.scandir`, `glob.glob` and `git ls-files`. A
  pattern it cannot place from the root (one built at run time, or relative
  to a subdirectory) is not compared, so declare such a reader's paths by hand.
- **Docs:** a document the mapper maps to no test.

The integration head is judged FIRST. Unless `HEAD` is the certified head and
the tree is clean, the verdict is `head-moved`, whatever `main` did: a commit or
merge after the gate, or an uncommitted change `--ff-only` would not land, has
not been through the gate. The exception is a clean `HEAD` that holds nothing
past the certified head but `main` merged in, by the rule `--advance` applies
(step 3 below): that is judged as the movement merged, with its recheck, so
checking again between the merge and `--advance` never asks for a second
`llm_qa.py all`. It is also `head-moved` when `main` is still the base but
`HEAD` does not contain it (the merge of `main` was backed out): `--ff-only`
would refuse, so the printed steps merge `main` back in first.

| Verdict      | Exit | When                                                                        | Recheck, run exactly as printed                                                                           |
| ------------ | ---- | --------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `head-moved` | 7    | `HEAD` is not the certified head, the tree is dirty, or `HEAD` lacks `main` | `llm_qa.py all` on a clean tree (after merging `main` when it is missing), then `main-moved` again        |
| `unmoved`    | 0    | `main` is still the batch base                                              | None: fast-forward                                                                                        |
| `docs-only`  | 5    | Every path is docs, or new commits change no file                           | `plan_qa docs_qa british_english sensitive_content repo_hygiene doc_truth doc_snippets handler_reference` |
| `targeted`   | 6    | A tested document, and nothing needing the full gate                        | `llm_qa.py changed` plus the docs-only tools `changed` does not run, with `--range <base>..<main>`        |
| `full-gate`  | 4    | Any full-gate path, or `main` was rewritten                                 | `llm_qa.py all`                                                                                           |

Exit 1 is no verdict: no base recorded, a bad ref, or git or the mapper failed.

For `docs-only`, `targeted` and `full-gate`, follow the loop the command prints,
in the integration worktree:

1. `git merge --no-edit main`.

2. The recheck.

3. `./scripts/qa/llm_qa.py main-moved --advance`. This moves the base to the
   newest `main` commit now merged in, and certifies `HEAD`, but only when all
   of these hold:

   - the tree is clean;
   - `HEAD` holds nothing since the certified head but `main` merged in. Every
     new commit must be a merge, and a merge may change only paths `main`
     moved. A conflict resolution that edits any other path needs
     `llm_qa.py all`;
   - the recheck that range needs PASSED on this exact tree, read from the same
     provenance `--read-only` trusts. For `targeted`, `changed_tests` must have
     run over exactly `<base>..<merged>`.

   Otherwise it refuses, says what is missing, and the base stays put.

4. `./scripts/qa/llm_qa.py main-moved` again. The base advanced, so it sees only
   newer movement.

When `main` is ALREADY merged into the certified head and the recheck already
passed on this tree, the command prints only steps 3 and 4. That is the path
after a red batch: `main` was merged before the gate re-ran, so the gate that
certified the head already covers `main`, and a second `llm_qa.py all` on the
same head would repeat it.

**If `git merge --ff-only` refuses**, `main` moved after the last check: run
`main-moved` again and follow the loop from there. It never re-runs anything
the advanced base, or a gate on the same tree, already covers.

**A `docs-only` or `targeted` landing leaves most tools unrecorded for the new
head.** Only the recheck's tools carry provenance for it, so a later
`llm_qa.py --read-only all` reads the rest STALE, and a release still needs its
own full run (RELEASING.md, step 1b).

**CI on the pushed head is the second line, not a substitute.** The recheck has
already run every test the mapper selects for a moved document: the tests that
name it, the declared readers (the `path_glob` rules above) and its dependents.
The checkers that sweep the whole tree (`docs_qa`, `plan_qa`, `doc_truth` and
the rest of the docs-only list) run in the recheck themselves. So a
`docs-only` or `targeted` landing relies on nothing CI does.
CI runs the whole suite on what was pushed, and a red CI is a red `main`,
handled at once. It is never a reason to skip the gate.

The path rules are defined once in `llm_qa.py` (`RUNTIME_READ_FILES`,
`RUNTIME_READ_ROOTS`, `judge_path`), and `tests/unit/qa/test_llm_qa_main_moved.py`
pins them, including every path the third review of Plan 00463 named.

**A red batch.**

- Find the branch that broke it: bisect the merge commits (`git bisect` over
  the first-parent chain), or build a trial branch without one branch at a time.
- A branch is never fixed inside the integration worktree. It goes back to its
  agent, and the fix lands on that branch.
- To take the fixed branch, merge it forward into the integration branch and
  run the gate again. No revert is involved, so nothing is lost.
- To DROP a branch, build a NEW integration branch from current `main`, merge
  the other ready branches, then `--start` and run the gate. In an agent team
  the new branch becomes the plan's parent (`worktree-plan-NNNNN-r2`), and the
  batch lands through it. Never drop a
  branch with `git revert -m 1` of its merge: once that lands, git treats the
  branch's commits as merged, and merging the fixed branch later silently
  leaves the reverted change out. The old integration branch is left for a
  human to delete: `git branch -d` refuses an unmerged branch, and `-D` is not
  an agent's to run.

**After the fast-forward, before the push**, restart the daemon in the main
checkout and check `bin/hooks-daemon status`. The gate ran under the integration
worktree's venv, so a dependency the batch added may be missing from the main
checkout's. If either step fails, **do not push**. The batch is still local, and
`main` was the batch base when it fast-forwarded, so
`git reset --keep "$(git rev-parse refs/integration/base/<branch>)"` puts local
`main` back exactly where it was. `--keep` refuses rather than discard an
uncommitted change, and it is not the denied `--hard`. Then fix the cause on a
branch and batch again. After the push, `main-moved --finish` removes the batch
refs, so run it last. After a push, `main` is never rewritten. Fix forward in
a new batch, or `git revert -m 1 <merge>` each batch merge. A reverted branch
can only come back by reverting that revert first, never by merging the branch
again.

**Any lock held around the gate must be released when the run exits**, even if
something the run started is still alive. A daemon restarted under the gate
inherits every inheritable descriptor, so a shell `flock` on fd 9 must close it
for the long-lived children: `hooks-daemon restart 9>&-`, and `exec 9>&-` before
a keepalive. Otherwise the daemon holds the lock and the next gate waits for
ever. `llm_qa.py`'s own run lock is opened non-inheritable, and
`tests/unit/qa/test_llm_qa_run_lock.py` pins that a daemon started during a run
does not keep it.

**The split:**

| Who                  | Runs                                                                                                                                                                                              | Hands over                                                                |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Sub-agent (any kind) | `./scripts/qa/llm_qa.py changed`, plus named tools the change calls for (`llm_qa.py handler_reference docs_qa ...`) and `pytest` on explicit test files or directories narrower than `tests/unit` | A commit hash and the targeted results                                    |
| Coordinator          | `./scripts/qa/llm_qa.py all` once, in an integration worktree from `main` with every ready branch merged `--no-ff`, before `main` moves                                                           | A fast-forward of `main`, or the failures sent back to the branch's agent |

`llm_qa.py changed` runs the fast static tools, the project handlers' own
tests, `docs_qa`, `plan_qa`, `shell_check`, `declared_invariant_pairs`, and
`changed_tests`: pytest on the tests mapped from every file changed since the
merge base, uncommitted and untracked files included. The runner's docstring
(`scripts/qa/run_changed_tests.py`) owns the mapping. A test file selects
itself. Any other file's coverage is the UNION of:

- its declared rule in `scripts/qa/changed_tests_map.yaml`;
- its MIRRORED tests (`src/<pkg>/a/b.py` maps to `tests/unit/a/test_b*.py`);
- the tests that refer to it: by path, by a path built from its parts, by a
  basename no other file shares, or by importing it;
- one hop of DEPENDENTS: each source that refers to it the same way adds its
  own unit tests.

References are read from the syntax tree, so a comment or docstring that
mentions a file does not count. A conftest's tests are its whole subtree.
**A `tools:` rule certifies lint only.** `*.md` mapped to `docs_qa`/`plan_qa`,
or `*.sh` to `shell_check`, says those checks ran. It says nothing about the
behaviour of a test that reads the file, and that test is selected through the
union.

**A changed file that maps to nothing FAILS the run**, and is named in the
summary with its reason. So does an empty change set. There are three reasons:

- `uncovered`: nothing refers to it.
- `too-broad`: its reach passes the cap of 40 test files. A hub module, a
  widely loaded config, and the root `tests/conftest.py` all hit this. Its own
  tests still run when they fit.
- `deleted-but-referenced`: it was deleted and a source still refers to it.

The remedy is, in order:

1. add the test the file lacks;
2. add a rule to the map;
3. pass `--allow-unmapped`, which passes and records that the full gate must
   cover it.

A `too-broad` file is the full gate's by definition, so `--allow-unmapped` is
its honest answer. `--base REF` changes the base, which defaults to the branch
`origin/HEAD` names. `changed` refuses to run on the base branch itself,
because there the merge base is HEAD.

**A targeted `pytest` names its paths.** This is a policy. The guard judges a
bare `pytest` by the directory it runs in, following the hook payload's `cwd`
and any `cd` in the same command: from the repository root it collects the
whole suite and is denied, and from `tests/unit/core` it collects only that
directory. Still write `pytest tests/unit/handlers/` rather than
`cd tests/unit/handlers && pytest`, so the command says what ran.

`llm_qa.py --read-only all` summarises the recorded results without running
anything, so a sub-agent may use it to read a result the coordinator produced.
Each run records per tool, in `untracked/qa/provenance.json`:

- the tree it judged (HEAD plus a digest of the uncommitted changes);
- the live verdict and exit code;
- the sha256 of the report the tool wrote.

A run deletes each tool's old report before running it. A read-only summary
**fails** a result in any of these cases:

- It was recorded for a different tree. This is marked `STALE`.
- Its report is missing or is not the one the run wrote.
- Its recorded exit code was non-zero.

So neither an old green run nor a crashed tool's leftover report reads as a
pass. A tree that changes during a run is said at the end of that run, because
those results certify no tree.

### The Automated Checks

`scripts/qa/run_all.sh` is the single source of truth for **which** checks exist
and how many. Run `./scripts/qa/llm_qa.py all` (the same suite, LLM-optimised
output) to see the current set. The notes below cover the ones with
requirements a reader needs to know in advance; they are not the full list, and
this section deliberately carries no count — an earlier version claimed seven
while the runner ran considerably more.

- **Magic Values** (`check_magic_values.py`) — hardcoded strings/numbers that
  should be constants: handler names, priorities, tool names, event types, tags
- **Format** (Black) / **Linter** (Ruff) — both auto-fix via
  `./scripts/qa/run_autofix.sh`
- **Type Check** (MyPy) — strict mode; every function annotated
- **Pyright** (`run_pyright_check.py`) — zero errors over what
  `pyrightconfig.json` scopes, with the same binary and config the language
  server runs, so any diagnostic an agent sees mid-edit is real. Installed as
  the pinned PyPI `pyright` dev extra (needs `node`); a missing binary FAILS
  the check with the install line, it never skips. Never reach zero with a
  suppression comment or a rule downgrade — see
  [development/LSP.md](development/LSP.md)
- **Tests** (Pytest) — **95% coverage minimum**. **No test may skip, xfail or
  early-return because the process is root.** This container, and the
  dogfood server, run as root, so a root-conditioned skip is a test that
  never runs where the work happens (Plan 00466 N56). Root bypasses file
  mode bits, so a permission check needs a different fault instead of a
  skip: monkeypatch the specific `os`/`open`/`Path` call to raise
  `PermissionError`, replace the file with a directory or a dangling
  symlink, or patch the exact predicate the code under test evaluates.
  `tests/integration/test_no_root_conditioned_skips.py` statically scans
  EVERY `.py` file under `tests/` — not just `test_*.py`/`conftest.py`, and
  with no exclusion for `tests/fixtures/` or any other directory; it is not
  opt-out. It classifies by data flow, not by name: a condition tainted by
  `geteuid`/`getuid`/`getegid`/`getgid`/`getresuid`/`getresgid`,
  `getpass.getuser`, a `pwd`/`grp` lookup, an env check of
  `USER`/`LOGNAME`/`HOME`/`SUDO_*`, `Path.home()`/`os.path.expanduser("~")`,
  `os.access(...)`, or `<expr>.stat().st_uid` is flagged however it reaches
  the condition — through an alias, a local variable, a module constant, or
  one level of same-module helper (a `def` or a zero-arg lambda, including a
  parameterised helper called with literal arguments). It fails on a
  `skipif`/`xfail`/`unittest.skipIf`/`skipUnless` decorator, an `IfExp`
  marker, a hand-written `if <root check>: skip/xfail/skipTest/return`, or a
  conftest `pytest_ignore_collect`/`pytest_collection_modifyitems`/
  `pytest_runtest_setup` whose control flow depends on one — **and
  independently** on any skip-like call whose stated *reason* names root,
  whatever its condition actually tests (the shape Plan 00351 found). A
  reference it cannot resolve (a cross-module import, a class attribute)
  whose own name suggests process identity is reported as unproven rather
  than silently passed. It also fails on a `pass`-only branch opposite a
  substantive one, and on an `assert` gated by identity with no `else` at
  all — both make the real check vacuous without ever calling anything
  skip-like, and both need to know which branch runs AS ROOT (only a no-op
  there is a problem, since this container is always root).
  **Known residual** (owner referral, not silently accepted): `try: <permission-bypassing op> except PermissionError: return` followed by an
  unconditional `pytest.skip(...)` has no syntactic root check at all — the
  root-dependence is only observable at runtime (root never raises
  `PermissionError`), which a static AST scan cannot see. A runtime probe
  (patch the identity calls, diff the collected/skipped set under both
  identities) would close it; nothing has attempted that yet. Tracked as
  `_KNOWN_RESIDUALS["try_except_permission_pass"]` in the detector's own
  test file, asserted to stay uncaught so a future fix flips that assertion
  red instead of drifting unnoticed.
- **Tests run under every Python in CI's matrix** (`run_test_matrix.py`,
  ledger 00466 N110). CI's QA job runs the suite once per version in
  `.github/workflows/qa.yml` (`jobs.qa.strategy.matrix.python-version`). A
  gate that ran one interpreter passed defects that exist only on another,
  so the tests stage reads that matrix at run time. Adding a version to CI
  widens the gate with no second edit, and an unreadable matrix fails the
  stage. How it runs:
  - The **primary** is the checkout's venv. It runs `run_tests.sh` as
    before: all of `tests/`, with coverage.
  - Every other matrix version is an **extra**. Each gets a venv at
    `untracked/qa-interpreters/py<X.Y>/`, synced from `uv.lock` by `uv`.
    These venvs sit outside the `untracked/venv-*` glob that the daemon's
    venv resolver scans, so one can never become the daemon's venv.
  - **Phase 1** runs the primary and each extra's `tests/unit` at the same
    time.
  - **Phase 2** then runs each extra's other directories, one version at a
    time. Those tests drive the checkout's single live daemon, so two
    versions at once would contend. The daemon is started before EACH of
    these runs if it has stopped: it exits after `idle_timeout_seconds`
    without traffic, and one run's later directories can outlast that
    (ledger 00466 N196).
  - If `uv` cannot find or install a version (for example, with no network),
    the stage **fails**. That version gets a `NOT RUN` line with the reason.
    The stage never passes on fewer versions than CI runs.
  - Lint, format, type checks and every other stage stay on the primary,
    because they do not depend on the interpreter version.
  - **Boundary:** a subprocess that a test spawns (`bin/hooks-daemon`, the
    live daemon) still resolves the checkout's primary venv. Only in-process
    code runs under the extra interpreter.
  - `tests.json` has an `interpreters` array with one entry per run: version,
    scope, counts, duration and error. Each extra's console log is at
    `untracked/qa/tests-py<X.Y>-<scope>.log`.
  - Every run, primary and extra, loads the
    `claude_code_hooks_daemon.qa.first_error_lines` pytest plugin. Each
    failed or errored test's record in `tests.json` carries the first line
    of its error as `reason`, and the gate's summary prints it after the
    node id (ledger 00466 N196).
  - `tests/conftest.py` loads that plugin, not a `-p` flag. A `-p` plugin
    is imported before pytest-cov starts, so the package code it imports is
    never measured: coverage fell to 92.61% with no test missing (N110).
  - To run the whole stage alone, use `./scripts/qa/llm_qa.py tests`.
    `run_tests.sh` alone runs only the primary.
- **Security** (Bandit) — zero HIGH/MEDIUM/LOW issues; only B101 is filtered
- **Dependencies** (Deptry) — missing (DEP001) and misplaced (DEP004)
- **Plan QA** / **Docs QA** (`run_corpus_qa.py`) — the `plan-qa --sweep` and
  `docs-qa --sweep` catalogues, run through the shipped CLI so QA cannot
  disagree with the gate it backs up. **ANY finding fails, at either
  severity**: the advise/block split decides whether a COMMIT is denied,
  while QA asks whether the tree is clean now. Fix the finding, or use the
  check's own configured allowlist — a finding left standing should be a
  decision, not an accident. A sweep that cannot run reports no-verdict
  rather than the empty result a clean sweep produces
- **Generated-Doc Drift** (`check_generated_doc_drift.py`) — regenerates
  `.claude/HOOKS-DAEMON.md` through `generate-docs` into a throwaway directory
  and fails when the committed body differs. A daemon restart never rewrites
  that file, so **any change to the handler set, a handler's priority or its
  docstring's first line needs `bin/hooks-daemon generate-docs` and the result
  committed alongside it**. The `> Generated on … (vX.Y.Z)` marker line is
  excluded from the comparison (it records the deployed-from version
  `scripts/upgrade.sh` reads) but its absence fails

### Success Criteria

EVERY check the runner runs must pass, with ZERO failures. `scripts/qa/run_all.sh`
is the single source of truth for which checks exist — this document deliberately
does not restate the list or the count, because a hardcoded number here went stale
the moment a check was added.

<!-- ssot-anchor: qa-summary-example -->

```
========================================
QA Summary
========================================
  Magic Values        : ✅ PASSED
  ... one line per check the runner ran ...

Overall Status: ✅ ALL CHECKS PASSED
```

**If ANY check fails**: Fix issues and re-run. Do not proceed until all pass.

---

## Sub-Agent QA (Layer 2)

### When to Run Sub-Agent QA

Sub-agent QA is required for:

- ✅ Architectural changes (new handlers, refactoring)
- ✅ Complex features (multiple files, cross-cutting concerns)
- ✅ Before merging significant work
- ✅ When using agent teams (see `CLAUDE/AgentTeam.md`)

Sub-agent QA is optional for:

- Small bug fixes (single file, trivial change)
- Documentation-only changes
- Configuration updates

### QA Agent Role (Gate 2)

**Primary Responsibility**: Verify code meets quality standards beyond automated checks.

**Spawning QA Agent**:

```python
Task(
    subagent_type="general-purpose",
    name="qa-agent",
    prompt="""You are a QA AGENT verifying code quality.

YOUR ROLE (QA - Gate 2):
Verify code meets quality standards (format, lint, types, coverage, security).

WORKFLOW:
1. cd to target directory
2. Run TARGETED QA: ./scripts/qa/llm_qa.py changed security
   (NOT `all`: the full suite is the coordinator's gate and is denied to
   sub-agents. See CLAUDE/QA.md "Full QA Is the Coordinator's Gate".)
3. Verify daemon: ./bin/hooks-daemon restart && status
4. Coverage is measured by the coordinator's full run. Read it with
   ./scripts/qa/llm_qa.py --read-only tests once that run exists.
5. Verify no security issues (Bandit must pass)
6. **Check library/plugin separation** (see checklist below)
7. Report "QA verified" OR "QA failed with details"

PASS CRITERIA:
- EVERY targeted check passes, and no changed source file is left unmapped
  without a reason
- Daemon restarts successfully
- No security issues
- Library/plugin separation maintained (no project-specific handlers in library)
- The coordinator's full run (every check, coverage ≥ 95%) still gates the merge

LIBRARY/PLUGIN SEPARATION CHECKLIST:
8. Library/Plugin Separation:
   - Scan src/claude_code_hooks_daemon/handlers/
   - Flag handlers that reference @CLAUDE/ paths
   - Flag "dogfooding" language (project-specific)
   - Flag project-specific functionality
   - Report violations found

LIBRARY HANDLERS (Generic, Reusable):
✅ Generic safety enforcement (destructive git, sed blocker)
✅ Generic QA enforcement (ESLint disable, TDD enforcement)
✅ Generic workflow patterns (plan numbering, npm commands)
✅ Tool usage guidance (web search year)
✅ Reusable by any project
✅ NO project-specific references

Examples: destructive_git, tdd_enforcement, sed_blocker, qa_suppression

PROJECT PLUGINS (Project-Specific):
⚠️ Project-specific functionality
⚠️ Dogfooding language/concepts
⚠️ References @CLAUDE/ documentation
⚠️ Specific to developing this project
⚠️ NOT reusable by other projects

Examples: dogfooding_reminder (references @CLAUDE/CodeLifecycle/Bugs.md)

VIOLATION DETECTION:
- grep -r "@CLAUDE" src/claude_code_hooks_daemon/handlers/
- grep -r "dogfooding" src/claude_code_hooks_daemon/handlers/
- Read handler code - does it reference project-specific docs/concepts?

REPORT FORMAT (PASS):
SendMessage(type="message", recipient="team-lead",
  content="QA complete. All checks pass. Coverage: XX%. Daemon restarts. Library/plugin separation verified: no violations. Ready for review.",
  summary="QA verified - pass")

REPORT FORMAT (FAIL):
SendMessage(type="message", recipient="team-lead",
  content="QA FAILED. Issues: [specific failures]. Library/plugin violations: [list violations]. Sending back to developer.",
  summary="QA failed - rejected")
"""
)
```

### Senior Reviewer Role (Gate 3)

**Primary Responsibility**: Verify work is COMPLETE per plan and architecturally sound.

**Spawning Senior Reviewer**:

```python
Task(
    subagent_type="general-purpose",
    name="senior-reviewer",
    prompt="""You are a SENIOR REVIEWER AGENT reviewing completeness and architecture.

YOUR ROLE (Senior Reviewer - Gate 3):
Verify work is COMPLETE per plan and architecturally sound.

WORKFLOW:
1. cd to target directory
2. Read CLAUDE/Plan/NNNNN-description/PLAN.md (goals, success criteria, phases)
3. Review all code: git log [branch] --stat
4. Verify ALL plan phases complete (not partial)
5. Check architecture (no duplication, correct patterns)
6. Verify success criteria met
7. Report "approved" OR "rejected with specific gaps"

CRITICAL CHECKS:
- If plan has N phases, ALL N must be complete
- If plan says "eliminate DRY", verify no duplication remains
- If plan says "42 tests", count that 42 exist
- If plan says "integrated with config", verify in config file
- Reject "ready for phase 2" (means incomplete)

REPORT FORMAT (APPROVED):
SendMessage(type="message", recipient="team-lead",
  content="Review complete. ALL phases done. Success criteria met: [list]. Architecture sound. Ready for honesty check.",
  summary="Review approved")

REPORT FORMAT (REJECTED):
SendMessage(type="message", recipient="team-lead",
  content="Review REJECTED. Incomplete: [gaps]. Phases X,Y,Z not done. Back to developer.",
  summary="Review rejected - incomplete")
"""
)
```

### Honesty Checker Role (Gate 4 - FINAL)

**Primary Responsibility**: Verify work delivers REAL VALUE, not just "looks complete". Detect theater, lazy solutions, and false claims.

**Spawning Honesty Checker**:

```python
Task(
    subagent_type="general-purpose",
    name="honesty-checker",
    prompt="""You are an HONESTY CHECKER AGENT auditing for theater and value delivery.

YOUR ROLE (Honesty Checker - Gate 4 - FINAL):
Verify work delivers REAL VALUE, not just "looks complete".
Detect theater, lazy solutions, substandard implementations, and false claims.

CRITICAL UNDERSTANDING:
- Code can pass tests and still be theater if it doesn't deliver real value
- Tests can exist but not prove anything meaningful (TDD theater)
- Handlers can "work" but be lazy/substandard implementations
- Features can be "done" but not really solve the problem

YOUR JOB: Ask "Does this ACTUALLY deliver the value implied by the feature?"

WORKFLOW:
1. cd to target directory
2. Read CLAUDE/Plan/NNNNN-description/PLAN.md (understand what VALUE should be delivered)
3. Perform DEEP VALUE AUDIT (not just code existence check)
4. READ ACTUAL CODE - don't just check files exist
5. READ ACTUAL TESTS - do they prove behavior or just exist?
6. Ask: "Would I accept this in code review or reject as lazy/incomplete?"
7. Report "genuine completion" OR "theater detected - REJECT"

THEATER DETECTION CHECKS:

Check 1 - Dead Code Theater:
  git grep "from.*[module_name] import"
  If module created but never imported → THEATER
  VALUE CHECK: Is code actually USED in application flow?

Check 2 - Config Theater:
  cat .claude/hooks-daemon.yaml
  If handler missing from config → THEATER
  VALUE CHECK: Is handler ACTIVE and intercepting events?

Check 3 - TDD Theater (Tests That Don't Prove Anything):
  grep -c "def test_" tests/path/to/test_file.py
  Compare to claimed count
  READ THE ACTUAL TESTS - do they test real behavior or just existence?

  Example TDD theater:
    def test_handler_exists():
        assert HandlerName() is not None  # Proves NOTHING

  VALUE CHECK: Do tests actually PROVE the feature works?

Check 4 - Handler Theater (Handlers That Don't Really Work):
  READ the actual handler code (don't just check it exists)
  VALUE CHECK: Does handler actually BLOCK/ALLOW/ADVISE correctly?

Check 5 - Lazy Solution Theater (Works But Is Substandard):
  VALUE CHECK: Is this a PROPER solution or lazy workaround?
  Ask: Would I accept this in code review or reject as lazy?

Check 6 - Goal Achievement Theater:
  Read plan goals: "eliminate DRY violations in handlers X,Y,Z"
  ACTUALLY CHECK handlers X,Y,Z for remaining duplication
  VALUE CHECK: Did they SOLVE the problem or just write code?

Check 7 - Phase Completion Theater:
  If plan has 8 phases, verify artifacts for ALL 8
  VALUE CHECK: Are phases actually DONE or just "started"?

Check 8 - Integration Theater:
  VALUE CHECK: Do all pieces WORK TOGETHER?

YOU CAN (and SHOULD):
- VETO entire branch if theater detected
- Reject even if tests pass (if tests are theater)
- Reject handlers that "work" but are lazy/substandard
- Call out solutions that technically work but aren't proper

REPORT FORMAT (GENUINE):
SendMessage(type="message", recipient="team-lead",
  content="Honesty check PASSED.

  VALUE VERIFICATION:
  - Code delivers real value (not just exists)
  - Tests PROVE feature works (not TDD theater)
  - Handler is PROPER implementation (not lazy)
  - Solution maintainable, follows patterns
  - Plan goals ACTUALLY achieved

  TECHNICAL VERIFICATION:
  - Code used in application flow
  - Handler in config and active
  - X tests exist, test real behavior
  - ALL phases complete
  - No theater detected

  APPROVED FOR MERGE.",
  summary="Genuine - approved")

REPORT FORMAT (THEATER):
SendMessage(type="message", recipient="team-lead",
  content="THEATER DETECTED.

  EVIDENCE:
  [Specific findings with code examples]
  - TDD theater: Tests don't prove behavior
  - Handler theater: Doesn't really solve problem
  - Lazy solution: Works but substandard/incomplete
  - Unachieved goals: Plan says X, code doesn't deliver

  VALUE ASSESSMENT:
  This does NOT deliver the value implied by feature.
  [Explain what's missing/wrong]

  ENTIRE BRANCH REJECTED. [Recommend: fix issues / redesign]",
  summary="Theater - REJECTED")
"""
)
```

---

## Acceptance Testing (Layer 3)

**Purpose**: Validate handlers work correctly in real-world scenarios before release.

**When Required**: Before production releases, after significant changes, for new handlers.

### Acceptance Testing Overview

**See `CLAUDE/AcceptanceTests/GENERATING.md` for complete acceptance testing guide.**

Acceptance testing is **agentic** - AI agents execute real-world test scenarios:

- Test definitions are in handler code (`get_acceptance_tests()` method)
- Playbooks are generated fresh from code (ephemeral, never committed)
- **AI agents execute the playbook** and validate behaviour
- Tests cover real-world usage scenarios
- Triple-layer safety (echo commands, hook blocking, fail-safe arguments)

### Running Acceptance Tests

```bash
# 1. Generate fresh playbook (ephemeral)
./bin/hooks-daemon generate-playbook > untracked/scratch/playbook.md

# 2. Execute tests manually following playbook
# ... test each scenario ...

# 3. Delete ephemeral playbook when done
rm untracked/scratch/playbook.md
```

### FAIL-FAST Cycle (CRITICAL)

**ANY bug found during acceptance testing = Complete the full cycle:**

```
Acceptance Testing → Find Bug → STOP → Fix with TDD → Run Full QA → Restart Daemon → RESTART FROM TEST 1.1
```

**Why restart from Test 1.1?**
Your fix might have affected earlier tests. Full re-run ensures no regressions.

**Process**:

1. Generate fresh playbook
2. Execute tests sequentially
3. **If bug found**: STOP immediately
4. Fix bug using TDD (write failing test, implement fix, verify)
5. Run FULL QA: `./scripts/qa/llm_qa.py all` (must pass 100%)
6. Restart daemon: `./bin/hooks-daemon restart`
7. **Regenerate playbook** (to reflect fix)
8. **RESTART from Test 1.1** (not from where you left off)
9. Continue until ALL tests pass with ZERO code changes

### Success Criteria

✅ All acceptance tests pass
✅ No code changes during testing run
✅ All handlers behave as expected in real scenarios
✅ Blocking handlers prevent dangerous operations
✅ Advisory handlers provide helpful context

### Acceptance Test Example

```python
def get_acceptance_tests(self) -> list[AcceptanceTest]:
    """Acceptance tests for destructive git handler."""
    return [
        AcceptanceTest(
            title="git reset --hard",
            command='echo "git reset --hard NONEXISTENT_REF"',
            description="Blocks destructive git reset",
            expected_decision=Decision.DENY,
            expected_message_patterns=[
                r"destroys.*uncommitted changes",
                r"permanently"
            ],
            safety_notes="Uses non-existent ref - harmless if executed",
            test_type=TestType.BLOCKING
        )
    ]
```

### Daemon Plugin Handlers

**Daemon plugins (handler modules) are automatically included** in generated playbooks.

All daemon plugin handlers MUST implement `get_acceptance_tests()` - empty arrays are rejected.

**See `CLAUDE/AcceptanceTests/GENERATING.md` for complete documentation.**

---

## Complete QA Workflow

### For Individual Work (No Agent Teams)

1. **During development**: Write tests first (TDD); iterate with
   `./scripts/qa/llm_qa.py changed`
2. **Before committing**: Run `./scripts/qa/llm_qa.py all` (you are the main
   thread here, so the full gate is yours)
3. **Fix any issues**: Use `./scripts/qa/run_autofix.sh` for format/lint
4. **Verify daemon**: `./bin/hooks-daemon restart && status`
5. **For significant work**: Spawn QA Agent for deep review

### For Agent Team Work

Follow the 4-gate verification process. Every gate agent runs TARGETED QA; the
coordinator's full gate is the last step before the merge:

```
Developer Agent
    ↓ Reports "ready for testing" (targeted QA green, work committed)
    ↓
Tester Agent (GATE 1) - Tests verified
    ↓
QA Agent (GATE 2) - Quality verified (including library/plugin separation)
    ↓
Senior Reviewer (GATE 3) - Completeness verified
    ↓
Honesty Checker (GATE 4) - Value verified
    ↓
Coordinator - batched integration gate: every ready branch merged --no-ff into
              one worktree from main, llm_qa.py all once on the combined head
    ↓
Fast-forward main (ONLY after all 4 gates AND the integration gate pass)
```

**See `CLAUDE/AgentTeam.md` for complete agent team workflow details.**

---

## Library vs Plugin Separation (CRITICAL)

### Library Handlers (src/claude_code_hooks_daemon/handlers/)

**Criteria**:
✅ Generic safety enforcement
✅ Generic QA enforcement
✅ Generic workflow patterns
✅ Tool usage guidance
✅ Reusable by any project
✅ NO project-specific references
✅ NO @CLAUDE/ doc references
✅ NO "dogfooding" language

**Examples**:

- `destructive_git` - Blocks dangerous git operations (generic)
- `tdd_enforcement` - Enforces test-first development (generic)
- `sed_blocker` - Blocks sed usage (generic)
- `qa_suppression` - Prevents QA suppression annotations across 11 languages (generic)

### Project Plugins (.claude/hooks/handlers/)

**Criteria**:
⚠️ Project-specific functionality
⚠️ Dogfooding language/concepts
⚠️ References @CLAUDE/ documentation
⚠️ Specific to developing this project
⚠️ NOT reusable by other projects

**Examples**:

- `dogfooding_reminder` - Reminds about bug handling protocol (project-specific)
  - References `@CLAUDE/CodeLifecycle/Bugs.md`
  - Uses "dogfooding" terminology
  - Only useful when developing hooks daemon itself

### How QA Agent Checks This

```bash
# Scan library handlers for violations
grep -r "@CLAUDE" src/claude_code_hooks_daemon/handlers/

# Check for dogfooding language
grep -r "dogfooding" src/claude_code_hooks_daemon/handlers/

# Manual review
# Read handler code - does it reference project-specific docs/concepts?
# Does it use terminology specific to this project?
# Would this handler be useful in other projects?
```

**If violations found**: Handler must be moved to plugin system.

---

## When to Run QA

### Always Required

- ✅ **Automated QA**: Before every commit
- ✅ **Automated QA**: After making code changes
- ✅ **Automated QA**: Before creating pull requests
- ✅ **Automated QA**: After merging branches

### Automated QA Only (Quick Check)

- Small bug fixes (single file)
- Documentation updates
- Configuration tweaks
- Trivial changes

### Automated + Sub-Agent QA (Full Review)

- New handlers or features
- Architectural changes
- Refactoring work
- Agent team deliverables
- Complex features

### Automated + Sub-Agent + Acceptance Testing (Pre-Release)

**Required before production releases:**

- ✅ New handler implementations
- ✅ Handler behaviour changes
- ✅ Major features
- ✅ Release candidates
- ✅ After significant changes to core functionality

**Acceptance testing validates real-world scenarios with AI agents executing the test playbook.**

---

## QA Failure Handling

### Automated QA Fails

1. Read failure details in `/workspace/untracked/qa/*.json`
2. Fix issues
3. Run `./scripts/qa/run_autofix.sh` (for format/lint)
4. Re-run the tools that failed (`./scripts/qa/llm_qa.py <tool> ...`), then
   `changed`. The coordinator re-runs `all` once the fix is handed back.
5. Repeat until all pass

### Coordinator's Full Gate Fails

- Send the failing check names and their JSON detail to the agent that owns
  the worktree. The agent fixes them with targeted runs and hands back a new
  commit.
- Re-run the full gate on the new head. Never merge a head the full gate has
  not passed.

### Sub-Agent QA Fails

**QA Agent (Gate 2) Fails**:

- Developer must fix quality issues
- Re-run targeted QA
- Restart from Gate 1 (Tester)

**Senior Reviewer (Gate 3) Rejects**:

- Developer must complete missing phases
- Address architectural issues
- Restart from Gate 1

**Honesty Checker (Gate 4) Rejects (THEATER)**:

- ENTIRE BRANCH REJECTED
- May require replanning
- Fix theater issues with proper implementation
- Restart from Gate 1

---

## Quick Reference

### Commands

```bash
# Full gate: the coordinator (main thread) only; run_all.sh is the human entry point
./scripts/qa/llm_qa.py all

# Targeted QA: what a sub-agent runs before handing over a commit
./scripts/qa/llm_qa.py changed

# Auto-fix format and lint issues
./scripts/qa/run_autofix.sh

# Individual checks
./scripts/qa/run_format_check.sh
./scripts/qa/run_lint.sh
./scripts/qa/run_type_check.sh
./scripts/qa/run_pyright_check.py --json
./scripts/qa/llm_qa.py tests       # the WHOLE suite, every Python in CI's matrix: coordinator only
./scripts/qa/run_tests.sh          # the WHOLE suite, this checkout's venv only: coordinator only
./scripts/qa/run_security_check.sh
./scripts/qa/run_dependency_check.sh

# Daemon restart verification
./bin/hooks-daemon restart
./bin/hooks-daemon status
```

### Success Indicators

✅ All 7 automated checks pass
✅ Coverage ≥ 95%
✅ Daemon restarts successfully
✅ No security issues
✅ Library/plugin separation maintained
✅ Sub-agent QA approves (if required)

---

## See Also

- **CLAUDE/AcceptanceTests/GENERATING.md** - Complete acceptance testing guide (agentic execution)
- **CLAUDE/AgentTeam.md** - Agent team workflow with QA gates
- **CLAUDE/CodeLifecycle/Features.md** - Feature development with QA integration
- **CLAUDE/CodeLifecycle/Bugs.md** - Bug fix workflow with QA verification
- **CONTRIBUTING.md** - Contribution guidelines and QA standards

---

**Maintained by**: Claude Code Hooks Daemon Contributors
**Last Updated**: 2026-02-09
