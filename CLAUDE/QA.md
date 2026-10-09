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

1. **Automated QA** (`./scripts/qa/llm_qa.py`) - Fast, deterministic checks, in the tiers below
2. **Sub-Agent QA** (via Task tool) - Deep architectural review and value verification
3. **Acceptance Testing** (Agentic) - Real-world scenario validation performed by AI agents before release

**CRITICAL**: All three layers are required for production-ready code. Each layer catches different types of issues.

---

## QA Tiers

This section is the one home for what QA runs, when, and who runs it. Other
documents point here; they do not restate it.

| Tier       | When                                   | Who                                        | What runs                                                                                                                    |
| ---------- | -------------------------------------- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| Targeted   | Every change, before its branch merges | The branch's agent; the coordinator checks | `./scripts/qa/llm_qa.py changed`                                                                                             |
| Post-merge | After a merge to `main`                | CI, off the host                           | The CI tier the pushed change needs (see "CI tiers"); `llm_qa.py changed --range <old>..<new>` runs the same mapping locally |
| Full       | Release preparation only               | The main thread, never a sub-agent         | `./scripts/qa/llm_qa.py all` on the clean release HEAD                                                                       |

Everyday work (a feature, a bug fix, a plan task, a merge to `main`) needs the
Targeted tier and nothing more. The Full tier is a release step
([development/RELEASING.md](development/RELEASING.md), Step 1b and Step 8), not a
step of any other workflow.

```bash
./scripts/qa/llm_qa.py changed     # TARGETED: static checks plus the tests the change maps to
./scripts/qa/llm_qa.py all         # FULL: release preparation, main thread only
./scripts/qa/llm_qa.py main-moved  # with a batch base recorded: what must re-run if main moved
```

Agents MUST use `llm_qa.py`, never `run_all.sh`: the `enforce_llm_qa` project
handler denies a direct `run_all.sh` invocation by an agent. `run_all.sh` remains
the human-at-a-terminal entry point and runs the same suite with verbose output.

### What the Targeted Tier Certifies

`llm_qa.py changed` certifies two things for the change set since the merge base
with the base branch (`--base REF`, default the branch `origin/HEAD` names;
`--range A..B` judges a range instead):

1. Every cheap repo-wide static check passed (listed under "The Automated
   Checks" below, `CHANGED_TOOL_NAMES` in `llm_qa.py`).
2. The tests mapped from every changed file passed, where mapped means a
   declared rule, a mirrored test, a test that refers to the file, or one hop of
   dependents (details below, and in `scripts/qa/run_changed_tests.py`).

It does NOT certify the rest of the pytest suite, coverage, the tests that run
under the other Pythons in CI's matrix, or the slower checks `changed` leaves out
(for example `security` is included but `dependencies` and `smoke_test` are not).
Those belong to CI and to the Full tier.

### The Unmapped and Too-Broad Fallback

A changed file that maps to no test FAILS `changed` and is named with its reason
(`uncovered`, `too-broad`, `deleted-but-referenced`; the remedy order is under
"The Targeted Tier in Detail"). `--allow-unmapped` lets the run pass, and the
report then records that the file's remaining reach is covered only by a
whole-suite run. Two things provide one:

- CI: in the docs and code tiers, a changed file the mapper cannot cover sends
  that one Python to the whole suite (`scripts/ci/full_suite_if_unmapped.bash`).
- The release's Full tier.

So `--allow-unmapped` is a statement that the change is not fully certified
locally, never a quiet pass. A branch that needed it says so when it hands over.
(The tool's own message still says "the coordinator's full gate must cover them";
that wording predates the tiers and is out of step with this document.)

### Before Merging: the Coordinator's Check

The coordinator merges a branch only with its targeted result in hand: the
commit hash the agent reports, with a green `llm_qa.py changed` on that commit.
When that result is missing (the agent was cut off, or reports no run), the
coordinator does not merge on trust and does not run the full gate. It runs the
static checks on the touched files, from the project root:

```bash
ruff check <touched python files>
black --check --target-version py311 <touched python files>
mypy <touched source files>
python3 scripts/qa/run_pyright_check.py --json   # pyright over what pyrightconfig.json scopes
python3 scripts/qa/audit_error_hiding.py
python3 scripts/qa/check_input_contract.py
shellcheck -x <touched shell files>
pytest <the touched tests, by path>
```

`run_pyright_check.py`, `audit_error_hiding.py` and `check_input_contract.py`
scan the whole project, not just the touched files (they take no file list); the
rest take the touched paths. None of them runs the whole test suite, so a
sub-agent may run them too. Then `llm_qa.py changed` on the merged head, which is
the same targeted run the agent owed, as soon as it can be had.

**The daemon checks this at merge time.** A passing `llm_qa.py changed` on a
clean tree (the whole selection, not a subset) records the commit it judged in
`refs/integration/changed-green/<branch>`. That is a git ref, not
`untracked/qa/provenance.json`, because the provenance file is written in the
checkout the run happened in (the branch's worktree) and the merge happens in
another; refs are shared by every worktree. A failing run of the whole
selection drops the record, and a dirty tree or a detached HEAD records
nothing (the run says so). `merge_qa_advisor` (Plan 00475 Task 4.2) reads it:
on a Bash `git merge` of a `worktree-*` or agent `agent-*` branch, local or `origin/`, whose head
the record does not name, it adds an advisory naming the head and the checks
above. It never blocks, and it is silent when the record matches, for any other
branch, for `--abort`/`--continue`/`--quit`, and when git cannot answer. Commit
before the run: an edit after it leaves the record on the older commit.

### Full QA Is the Coordinator's Gate; Sub-Agents Run Targeted QA

The Full tier runs **once, on the main thread, when a release is prepared**
([development/RELEASING.md](development/RELEASING.md)). A sub-agent never runs
it. This is enforced: in a sub-agent,
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
before merging. The old per-checkout run lock (Plan 00262) could not help
across worktrees; the host-wide lock below replaces it. A coordinator gate that still ran once per branch, one at a time,
only moved the queue: N ready branches cost N full runs, N pushes and N CI runs.
Running it once per release removes the queue.

**Why the Targeted tier is wide enough to stand alone.** Some checks break from
changes far away: guidance coverage, docs QA, plan QA, the handler reference,
generated-doc drift and the acceptance probes. So `changed` runs EVERY cheap
repo-wide static check whatever changed, and selects the playbook harness
whenever handler code changes. What the Targeted tier defers is the part of the
pytest suite no mapped test reaches, and CI runs that on every push to `main`
in the tier the change needs. A break that only exists when two branches meet
is caught by running `changed` over the combined head (`--base main` in the
integration worktree) and by CI. A red CI is a red `main`, handled at once.

### The Batched Integration Gate

This is the mechanism for running the Full tier on an integration branch and
moving `main` only to a head that run certified. Use it when a full gate is run
on a branch that is not `main` itself, for example a release candidate assembled
from several ready branches. The release steps
([development/RELEASING.md](development/RELEASING.md)) run the same gate on the
clean release HEAD. The everyday merge needs none of it: a green targeted run on
the branch or the combined head is enough.

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

Step 5 as a script. `|| rc=$?` keeps a non-zero verdict from ending a
`set -euo pipefail` script before the `case` runs, and each non-zero branch
exits with the verdict, so nothing after it runs. It fast-forwards to the
certified sha, never the branch name. Here `my-integration-branch` stands for the
integration branch and `/workspace` for the main checkout:

```bash
rc=0
./scripts/qa/llm_qa.py main-moved || rc=$?
case $rc in
  0) # unmoved: fast-forward main to EXACTLY the certified head, by its sha
     certified=$(git rev-parse refs/integration/certified/my-integration-branch)
     git -C /workspace merge --ff-only "$certified" ;;
  7) # head-moved: run the printed steps on a clean tree, then check again
     echo "head-moved: run the printed steps, then the gate on a clean tree"
     exit "$rc" ;;
  4|5|6) # full-gate / docs-only / targeted: run the printed recheck, then --advance
     echo "main moved: run the printed recheck and --advance"
     exit "$rc" ;;
  *) # 1: no verdict (no base, bad ref, git or the mapper failed): stop
     echo "no verdict: fix the cause before anything lands"
     exit "$rc" ;;
esac
```

`tests/integration/test_main_moved_branching_survives_errexit.py` executes this
block under `set -euo pipefail` for every exit code `main-moved` has.

**One QA process at a time on the host.** Every `llm_qa.py` run that executes
tools (`all`, `changed`, or named tools) takes ONE host-wide lock,
`<git-common-dir>/hooksdaemon-full-qa.lock`, before its first tool starts.
The common git dir is shared by every worktree, so a run in one worktree
queues behind a run in another. The wait is bounded and queues instead of
refusing:

- While the lock is held elsewhere the run prints to stderr, at once and then
  every minute, `llm_qa: waiting for the host-wide QA lock ... held by pid N in <checkout>`. The pid and checkout come from a stamp the holding
  `llm_qa.py` writes into the lock file and are shown only while that pid is
  alive. A holder that is not `llm_qa.py` (a bare `run_tests.sh`) stamps
  nothing and is reported as unknown.
- The wait is `FULL_QA_LOCK_WAIT_SECONDS`, default 600, the same variable
  `run_tests.sh` uses. A value that is not a non-negative number is an error,
  exit 1.
- **Exit 4 (`EXIT_LOCK_TIMEOUT`)**: the lock was still held when the wait ran
  out and NO tool ran. It is distinct from 1 (a check failed) and from 3
  (the retired "busy" refusal of the per-checkout lock, never reused). The
  message names the holder and says not to delete the lock file: `flock`
  drops the lock when its holder exits, so a stale file is not a held lock.
  A live orphan that inherited the descriptor is what can hold it.
- Not locked, because they run no tools: `--read-only`, `--help`, and
  `main-moved`. `--read-only` is how you inspect the run you are queued
  behind.
- `hooks-daemon restart` warns when a run holds this lock and the stamp names
  this checkout (or names nobody).

**The lock is one lock, and a whole-suite run inside it does not wait on
itself.** `llm_qa.py` passes its locked descriptor to every tool it starts
(`pass_fds`, plus `FULL_QA_LOCK_INHERITED_FD` as a hint for the shell side).
`tests/conftest.py` (`claude_code_hooks_daemon.qa.full_qa_gate`) refuses a
whole-suite-sized pytest COLLECTION outright unless it holds that lock,
proven by an inherited file descriptor on the lock file and `flock` on that
very descriptor -- never by the variable. That is the sink every route ends up
at, regardless of what launched it, and it is why a sub-agent's
`subagent_full_qa_blocker` handler, a friendly first line that cannot
enumerate every launcher, is not the guarantee. `scripts/qa/run_tests.sh`
recognises the inherited descriptor and does not re-acquire, and
`run_test_matrix.py` does the same (`acquire_full_qa_lock(..., reuse_inherited=True)`). A bare `run_tests.sh`, and CI, acquire it themselves.
`llm_qa.py` runs under the system `python3` before any venv and cannot import
the daemon package, so it opens the same file with its own stdlib code;
`tests/unit/qa/test_llm_qa_host_lock.py` pins that the two agree. See
`src/claude_code_hooks_daemon/qa/full_qa_lock.py` and Plan 00463's "Round 9"
note for the design.

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
CI runs the tier the pushed change needs (below), and a red CI is a red
`main`, handled at once. It is never a reason to skip the gate.

### CI tiers

`.github/workflows/qa.yml` starts with a `classify` job. It runs
`scripts/ci/classify_changes.py` over the changed range and prints `tier=<x>`.
`scripts/ci/emit_tier.bash` picks the range: on a push, from the head sha of the
newest `main` run of this workflow that reached a verdict (not the sha before
the push, which a cancelled run may have left untested) to the pushed sha; on a
pull request, from the merge base to the PR tip. The rules live in
`classify_changes.py`'s one table, tested in
`tests/unit/scripts/test_classify_changes.py`.

| Tier   | When                                                                                                                                                                                                                          | What runs                                                                                                                                                              |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `docs` | every changed path is `*.md`                                                                                                                                                                                                  | One Python (3.11): `llm_qa.py docs_qa plan_qa changed_tests --range`. The `shell` and `daemon-load` jobs are skipped.                                                  |
| `code` | anything else                                                                                                                                                                                                                 | One Python (3.11): black, ruff, mypy, pyright, `llm_qa.py changed --range`, bandit, deptry, plus `shell` and `daemon-load`.                                            |
| `full` | `pyproject.toml`, `uv.lock`, anything under `.github/`, `.claude/hooks-daemon.yaml`, `scripts/qa/changed_tests_map.yaml`, any `conftest.py`; an empty change set; an unknown base (no earlier verdict run, or not in history) | The three-Python matrix (job `qa`, unchanged), plus `shell` and `daemon-load`. Also every night on `main` (`schedule`) and on `workflow_dispatch`, which have no base. |

Markdown is narrowed, never skipped: tests read the plan index, ledgers and
docs, so the docs tier still runs the mapper's tests for the changed files.
In the `docs` and `code` tiers a changed file the mapper cannot cover
(unmapped, which includes `too-broad`) sends that one Python to the whole
suite (`scripts/ci/full_suite_if_unmapped.bash`) rather than passing on tests
that did not reach it.

**A `docs` or `code` green is NOT release evidence.** Plan 00359's release
slate gate looks for a green run on HEAD's exact sha and does not yet tell the
tiers apart. A release needs the full-matrix run: dispatch the workflow
(`gh workflow run qa.yml`) on the release commit, or use the nightly, and cite
that run. Making the gate require it is open work (Plan 00475 Task 3b.2).

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
ever. `llm_qa.py`'s own lock descriptor is opened non-inheritable and passed only
to the tool it is running, and
`tests/unit/qa/test_llm_qa_run_lock.py` pins that a daemon started during a run
does not keep it.

**The split:**

| Who                  | Runs                                                                                                                                                                                                                   | Hands over                                                                |
| -------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Sub-agent (any kind) | `./scripts/qa/llm_qa.py changed`, plus named tools the change calls for (`llm_qa.py handler_reference docs_qa ...`) and `pytest` on explicit test files or directories narrower than `tests/unit`                      | A commit hash and the targeted results                                    |
| Coordinator          | The same `llm_qa.py changed` over the combined head when it merges branches (`--no-ff`), or the static checks under "Before Merging" for a branch with no targeted result. `llm_qa.py all` only at release preparation | A fast-forward of `main`, or the failures sent back to the branch's agent |

### The Targeted Tier in Detail

`llm_qa.py changed` runs EVERY cheap repo-wide static check on every run,
whatever changed, because a change far away can break any of them
(`CHANGED_TOOL_NAMES` in `llm_qa.py` is the list; on one host the static checks
took about 460 s before `changed_tests`, per Plan 00475's timings): `magic_values`, `format`, `lint`, `type_check`, `pyright`,
`error_hiding`, `eacces_safe`, `shell_check`, `shell_audit`, `repo_hygiene`,
`doc_truth`, `doc_snippets`, `plan_qa`, `docs_qa`, `generated_doc_drift`,
`handler_reference`, `hook_contract`, `input_contract`, `project_handlers` (the
project handlers' own tests), `declared_invariant_pairs`, `skill_refs`,
`canonical_callers`, `authored_path_stat`, `signal_targets`,
`unreachable_handle_branch`, `fail_open_inventory`, `security`,
`capture_corruption`, `dangerous_invocation_corpus`, `python_var_guidance`,
`skip_list_substring`, `sensitive_content`, `british_english`, `git_history`,
`github_urls` and `semgrep`. None needs a live daemon. Deliberately absent:
`security_downgrade_flags` (about 49 s), `smoke_test`, `tests`, and
`dependencies` (it checks the local venv against `uv.lock` and runs
`uv lock --check`, so it judges the host rather than the tree). It then
runs `changed_tests`: pytest on the tests mapped from every file changed since
the merge base, uncommitted and untracked files included. A change to handler code
(`src/claude_code_hooks_daemon/handlers/**`) also selects
`tests/acceptance/test_playbook_harness.py`, through a rule in
`changed_tests_map.yaml`, because the handlers' acceptance probes are dispatched
only by that harness. The runner's docstring
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
3. pass `--allow-unmapped`, which passes and records that a whole-suite run
   must cover it (see "The Unmapped and Too-Broad Fallback").

A `too-broad` file is beyond what mapped tests can certify, so
`--allow-unmapped` is its honest answer. `--base REF` changes the base, which
defaults to the branch `origin/HEAD` names. `changed` refuses to run on the base branch itself,
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
pass. Each step writes its record the moment it finishes and judges the tree
just before and just after that step, so a tree that changes during one step
is said at once and taints only that step's record.

An interrupted run (for example a host reboot) is resumed with
`llm_qa.py all --resume`. Each tool whose recorded result PASSED on the
identical tree (and whose report is still the one that run wrote) is printed as
reused and not run; a failed, stale or missing record is always re-run. Reused
steps count in the verdict and show their recorded duration, marked reused.
`--resume` takes the full-QA lock like any run, and cannot be combined with
`--read-only`.

The `tests` step is most of the gate, so `--resume` also reaches inside it.
`run_test_matrix.py` writes a checkpoint per matrix leg
(`untracked/qa/leg-py<version>-<scope>.checkpoint.json`, written by temp file and
rename) the moment that leg finishes, keyed to the tree just before and just
after it. On a resumed run a leg is reused only if it exited 0 and passed on the
identical tree and the log (or, for the primary, the saved report copy) is still
the one it wrote; a failed, stale or missing leg runs again, and a leg that
starts drops its old checkpoint. The primary leg (3.11, full suite, the only one
with coverage) is reused or re-run as one unit, so coverage and its 95%
threshold are never split. Reused legs stay in `tests.json` `interpreters[]` with
`"reused": true` and their recorded counts and `slowest_tests`. A normal `all`
never reuses a leg: `llm_qa.py` passes `--resume` to the `tests` tool only when
it was itself resumed.

Each leg is itself a list of **shards**: named slices of `tests/` declared once
in `scripts/qa/test_shards.yaml` (`paths`, or `remainder_of` a directory for
everything no other shard claims). A shard is the unit that is checkpointed
(`leg-py<version>-<scope>-<shard>.checkpoint.json`), so a reboot mid-primary
loses one shard, not the hour-long leg, and `--resume` re-runs only the shards
not green on the identical tree. Shards run one after another within a leg. The
primary runs every shard; the extra interpreters' `unit` scope is the shards
whose `scope` is `unit` (exactly `tests/unit`) and `rest` the others.
`tests/unit/qa/test_suite_shards.py` fails if any test file under `tests/` is
in no shard or in two, so sharding can never drop or double-run a test; a new
test directory lands in a `remainder_of` shard without editing the file.

Coverage is still judged on the whole suite, at the unchanged `fail_under`
(95) in `pyproject.toml`. `run_tests.sh --shard` makes each primary shard write
its own coverage data file (`untracked/qa/.coverage.<shard>`, via the
`COVERAGE_FILE` environment variable, which coverage.py reads as the DATA file;
the JSON report path is the separate `COVERAGE_JSON`) and judge no threshold.
The data file is hashed into the shard's checkpoint with its report. Once every
primary shard has run or been reused, `run_test_matrix.py` runs
`coverage combine --keep` over them, writes `coverage.json` and takes the
`coverage report` fail-under verdict from the combined data; a shard with no
data file means coverage is not judged and the stage fails. `parallel = true`
stays off in the coverage config. `tests.json` keeps its shape (counts summed
over shards, the failed tests, `coverage`, merged `slowest_tests`); each
`interpreters[]` entry for a sharded leg adds a `shards` list, one record per
shard with its own counts, duration and `reused` flag.

### The Automated Checks

`scripts/qa/run_all.sh` is the single source of truth for **which** checks exist
and how many. `./scripts/qa/llm_qa.py all` runs the same suite with
LLM-optimised output, and is the Full tier's command: release preparation, main
thread only. The Targeted tier runs the `CHANGED_TOOL_NAMES` subset of it. The notes below cover the ones with
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

EVERY check the tier runs must pass, with ZERO failures: the `changed` set for
the Targeted tier, every check the runner runs for the Full tier.
`scripts/qa/run_all.sh` is the single source of truth for which checks exist — this document deliberately
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
   (NOT `all`: the full suite is a release step, the main thread's, and is
   denied to sub-agents. See CLAUDE/QA.md "QA Tiers".)
3. Verify daemon: ./bin/hooks-daemon restart && status
4. Coverage (95% minimum) is measured by the Full tier and by CI's full
   matrix, not by a targeted run. Do not report a coverage figure you did not
   read from one of those.
5. Verify no security issues (Bandit must pass)
6. **Check library/plugin separation** (see checklist below)
7. Report "QA verified" OR "QA failed with details"

PASS CRITERIA:
- EVERY targeted check passes, and no changed source file is left unmapped
  without a reason
- Daemon restarts successfully
- No security issues
- Library/plugin separation maintained (no project-specific handlers in library)
- The release's full run (every check, coverage ≥ 95%) still gates the release

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
Acceptance Testing → Find Bug → STOP → Fix with TDD → Run QA → Restart Daemon → RESTART FROM TEST 1.1
```

**Why restart from Test 1.1?**
Your fix might have affected earlier tests. Full re-run ensures no regressions.

**Process**:

1. Generate fresh playbook
2. Execute tests sequentially
3. **If bug found**: STOP immediately
4. Fix bug using TDD (write failing test, implement fix, verify)
5. Run QA (must pass 100%): `./scripts/qa/llm_qa.py changed`. When the
   acceptance run is part of a release preparation, the main thread runs the
   Full tier instead (`./scripts/qa/llm_qa.py all`, RELEASING.md)
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
2. **Before committing**: Run `./scripts/qa/llm_qa.py changed`. Being the main
   thread does not make the full gate yours to run here: it is a release step
3. **Fix any issues**: Use `./scripts/qa/run_autofix.sh` for format/lint
4. **Verify daemon**: `./bin/hooks-daemon restart && status`
5. **For significant work**: Spawn QA Agent for deep review

### For Agent Team Work

Follow the 4-gate verification process. Every gate agent runs TARGETED QA, and
so does the coordinator before the merge:

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
Coordinator - every ready branch merged --no-ff into one worktree from main,
              llm_qa.py changed on the combined head (or the static checks
              under "Before Merging" for a branch with no targeted result)
    ↓
Fast-forward main (ONLY after all 4 gates AND the combined targeted run pass)
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

- ✅ **Targeted QA** (`llm_qa.py changed`): Before every commit
- ✅ **Targeted QA**: After making code changes
- ✅ **Targeted QA**: Before creating pull requests
- ✅ **Targeted QA**: Before merging branches, over the combined head
- ✅ **Full QA** (`llm_qa.py all`): Release preparation only, main thread

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
   `changed`.
5. Repeat until all pass

### The Full Gate Fails (Release Preparation)

- Send the failing check names and their JSON detail to the agent that owns
  the worktree. The agent fixes them with targeted runs and hands back a new
  commit.
- Re-run the full gate on the new head. Never release a head the full gate has
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
# Targeted QA: every change, before it merges (sub-agents and the coordinator)
./scripts/qa/llm_qa.py changed

# Full gate: release preparation, main thread only; run_all.sh is the human entry point
./scripts/qa/llm_qa.py all

# Auto-fix format and lint issues
./scripts/qa/run_autofix.sh

# Individual checks
./scripts/qa/run_format_check.sh
./scripts/qa/run_lint.sh
./scripts/qa/run_type_check.sh
./scripts/qa/run_pyright_check.py --json
./scripts/qa/llm_qa.py tests       # the WHOLE suite, every Python in CI's matrix: main thread only
./scripts/qa/run_tests.sh          # the WHOLE suite, this checkout's venv only: main thread only
./scripts/qa/run_security_check.sh
./scripts/qa/run_dependency_check.sh

# Daemon restart verification
./bin/hooks-daemon restart
./bin/hooks-daemon status
```

### Success Indicators

✅ Every check of the tier in use passes
✅ Coverage ≥ 95% (Full tier and CI's full matrix)
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
