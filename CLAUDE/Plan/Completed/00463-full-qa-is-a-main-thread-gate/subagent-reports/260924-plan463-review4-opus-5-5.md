# Plan 00463 fourth review: verification of the review 3 fixes (Opus 5.5)

**Scope.** Branch `worktree-plan-463-full-qa-gate` at `bc804523` ("Plan 00463: fix every finding in
review 3"). I checked the implementer's claims in `260924-plan463-impl-opus-5-5.md` ("Review 3
fixes") and the two newest 00463 journal entries against review 3's R1 to R13. The review was
read-only: nothing tracked was edited in any worktree.

**How it was probed.** Every scenario ran for real in a scratch clone of `bc804523`
(`untracked/scratch/probe_463r4_repo`, plus a second worktree `probe_463r4_repo_m`). `main-moved`
was run with a scenario branch as `MAIN_REF`, from integration branches recorded with `--start`. The
documented loop (merge, recheck, `--advance`, `main-moved`) was followed to the end where it
mattered. The probes are all under `/workspace/untracked/scratch/probe_463r4_*`:

- `probe_463r4_main_moved.sh` and `_out.txt`: 13 path classes through the real `main-moved`.
- `probe_463r4_loop_*.txt`: end-to-end loop runs (docs-only, targeted, wrong range, stale record,
  delete, rename, dirty tree).
- `probe_463r4_doc_commands.py` and `_out.txt`: the new doc blocks through the live PreToolUse chain
  (main thread, library and project handlers), built like
  `test_full_qa_gate_is_never_deadlocked.py`.
- `probe_463r4_blocker.py`, `probe_463r4_blocker_cwd.py` and `probe_463r4_blocker_out.txt`: 166
  commands through `subagent_full_qa_blocker.matches()` with a sub-agent event and the live YAML
  patterns.
- `probe_463r4_lexer_compare.py`: 463's `_invocations` beside 464's `lex()`.
- `probe_463r4_setup_worktree.py`: new printed shapes against the rewritten R3 test.

**Targeted tests (no full suite):** in the 463 worktree, `test_llm_qa_main_moved.py`,
`test_llm_qa_provenance.py`, `test_run_changed_tests.py`, `test_llm_qa_changed.py`,
`test_setup_worktree_qa_guidance.py`, `test_subagent_full_qa_blocker.py` and
`test_orchestrator_simulate.py` all passed (518). In the clone, the `targeted` recheck's
`changed_tests` ran the 6 mapped test files and all 474 tests passed.

**Counts.**

- Review 3 findings: 8 VERIFIED, 5 PARTIAL (R1, R2, R3, R5, R7), 0 NOT FIXED.
- New findings: 0 blocker, 2 major, 6 minor, 4 nit.

---

## R1 to R13

| #   | Verdict  | Evidence                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| --- | -------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| R1  | PARTIAL  | Every class the brief named is judged correctly in real runs. A journal edit is `docs-only` (exit 5). `CLAUDE/HANDLER_DEVELOPMENT.md` is `targeted` (6 test files), and so is `CLAUDE/Plan/README.md` (32 test files). Code, a `docs/*.md` symlink to `src/`, root `CLAUDE.md`, `.claude/rules/*.md`, a plan-folder `conftest.py` and nested `CLAUDE/Plan/CLAUDE.md` (`too-broad`) are all `full-gate` (exit 4). A rename or delete of a linked doc is `docs-only`, and the recheck catches it: `docs_qa` fails and `--advance` refuses. The `targeted` recheck really runs the mapped tests (474 passed). Runtime-read markdown outside `RUNTIME_READ_*` (`CLAUDE/PlanWorkflow.md`, `CLAUDE/core/*.core.md`, the plan templates, `docs/guides/HANDLER_REFERENCE.md`, `HOOK-CONTRACT-REFRESH.md`) maps to tests or reads `too-broad`. **Residual: tests that read documents by glob are invisible to the mapper (N1, major).** |
| R2  | PARTIAL  | The base survives in `refs/integration/<branch>/base`, and the loop ends. `--advance` refuses a failing recheck (`docs_qa: the recorded run did not pass`) and a stale record from before the merge ("recorded at 687d1a58, but HEAD is 1e8318c2"). It also refuses a wrong range and a symbolic spelling of the right range, and the `update-ref` carries an old-value check. **Residual: nothing binds `unmoved` or `--advance` to the head that lands (N2, major).**                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| R3  | PARTIAL  | All nine injected cases, including every row of review 3's table, are caught. It still misses shapes that avoid the start words (N7, minor).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| R4  | VERIFIED | An empty commit on `main` reads `docs-only` (exit 5), not `unmoved`. `unmoved` is `rev-parse main == base`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| R5  | PARTIAL  | AgentTeam.md is one model: the parent is the integration branch, and the gate runs once in STEP 1. The :1186 run is gone, rejects go back to the child, and STEP 5 branches on the exit code. The `case $?` block branches correctly as written, but not under the `set -euo pipefail` the daemon's own advisory asks for (N3, minor). Leftover inconsistencies are in N11. **The MAIN_REF deviation is agreed; see below.**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| R6  | VERIFIED | Both nested conftests now read `too-broad`: `tests/integration/conftest.py` reaches 181 test files and `tests/unit/plan_qa/conftest.py` reaches 52.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| R7  | PARTIAL  | Every form review 3 named is now DENIED: `py.test`, `coverage run -m pytest`, `python -m`, `tests/./unit`, `tests/unit/qa/..`, `cd tests && pytest unit` and `cd tests/unit && pytest ../unit`. So are env prefixes, `env -i`, `bash -c`/`-lc`, `timeout`, `nice`, `nohup`, `exec`, `command`, `time`, `stdbuf`, `uv`/`pdm`/`pipenv`/`poetry run`, bare `pytest`, `(cd tests && pytest)`, `pushd`, `bash <<'EOF'` and `cat <<'EOF' \| bash`. Every targeted form in the brief stays ALLOWED, including `timeout 600 pytest tests/unit/qa`, `cd tests/unit/qa && pytest file.py`, `--read-only all`, `changed --range` and mentions in commit messages, `echo` and `grep`. The worktree has no Makefile, so `make test` does not apply. **Residual: unlisted whole-suite spellings and a false deny (N4 to N6, N8 to N10).**                                                                                                    |
| R8  | VERIFIED | `_run_tools` takes `output_digest(output)` straight after `run_tool` (llm_qa.py:1884-1885). `recorded_failure_reason` fails a recorded `passed: false` or a non-zero exit.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| R9  | VERIFIED | `git reset --keep "$(git rev-parse refs/integration/<b>/base)"` is ALLOWED by the live chain. It is also semantically right: `unmoved` means `main == base`, so the base is exactly `main`'s position before the fast-forward. QA.md forbids dropping a branch with `revert -m 1` and states the revert-the-revert caveat. A red batch is rebuilt on a new branch.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| R10 | VERIFIED | The printed docs recheck is `plan_qa docs_qa british_english sensitive_content`, without `format`. QA.md:135-138 states the STALE consequence.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| R11 | VERIFIED | `--read-only main-moved X` dispatches (exit 5). `lint main-moved` is refused with the usage line. Exits 0, 4, 5 and 6 were all observed.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| R12 | VERIFIED | A `docs/probe-link.md` symlink reads `full-gate` ("a symlink"), and so does a plan-folder `conftest.py` ("not a document").                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| R13 | VERIFIED | `orchestrator_simulate.py:261` prints "the call names no tool", and PLAN.md has no over-long prose line.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

**The deviation from R5 (the parent is not passed as MAIN_REF): agreed.** In the one-model
AgentTeam flow there is no gate at child to parent. The gate runs in the parent after `main` is
merged in, and what lands is `git merge --ff-only` of `main` to the parent. So the ref whose
movement invalidates the gate against what lands is `main`, and the default is right.

Passing the parent would be meaningless as well as wrong. `start_batch` records
`merge-base HEAD <ref>`, and with HEAD on the parent that is the parent itself, so every later
check would read `unmoved`.

Review 3's concern does survive in another form. The other thing that must not move after the gate
is the integration head itself, and nothing checks it. That is N2(a).

---

## New findings

### N1. MAJOR (R1 residual): documents read by glob pass as `docs-only` or `targeted`, and a red head lands

**Where:**

- `scripts/qa/llm_qa.py`, `judge_path`. It trusts the mapper's answer for a document.
- `scripts/qa/run_changed_tests.py`. The reference search sees only tests that name a file.
- `scripts/qa/changed_tests_map.yaml:35-37`. The rule `*.md` → `tools: [docs_qa, plan_qa]` says "no
  test imports it".
- `CLAUDE/QA.md:140-142`: "Every test that reads a moved document has already run in the recheck,
  because the mapper names those tests."

**The gap.** Several tests read the real document corpus by glob, which a by-name reference search
cannot see:

- `tests/integration/test_documented_commands_are_not_self_denied.py`: `DOCUMENT_GLOBS` covers
  `CLAUDE/*.md`, `CLAUDE/development/*.md`, `CLAUDE/CodeLifecycle/*.md`, `docs/**/*.md` and the
  skill tree.
- `tests/unit/scripts/test_branch_install_gate_is_unadvertised.py`: `docs/**/*.md`.
- `tests/integration/test_repo_hygiene_check.py`: the whole tracked tree through `git ls-files`.

**Reproduced end to end** (`probe_463r4_main_moved.sh`, `probe_463r4_loop_doctools.txt`):

1. `main` gains `docs/guides/PROBE_NEW_GUIDE.md`. It contains a `bash` fence with
   `curl -fsSL https://example.com/install.sh -o /tmp/install.sh`.
2. `test_documented_commands_are_not_self_denied.py` FAILS on that tree: 1 failed, 3 passed,
   naming `docs/guides/PROBE_NEW_GUIDE.md:6`.
3. `main-moved` says `docs-only` ("no test reads it"), exit 5.
4. The printed loop is followed. `git merge --no-edit`, then the doc recheck passes 4/4, then
   `--advance` gives "BATCH BASE: advanced", then `main-moved` gives `VERDICT: unmoved` with
   "git merge --ff-only integ_glob2, then push".
5. The head that would land fails a test. Only CI catches it, after the push.

**The same happens for an existing document** (`m_mod_existing`):

- The curl line appended to `docs/guides/TROUBLESHOOTING.md` reads `[docs] no test reads it`.
- The same line appended to `CLAUDE/Worktree.md` reads `targeted`. But the 5 tests selected for it
  (`test_pre_tool_use_safety`, `test_all_handlers_response_validation`,
  `test_handler_workspace_scope`, `test_worktree_file_copy` and `test_core_doc_deployment`) do not
  include the test that fails.

So the invariant review 3 R1 asked for still does not hold for this class: a change that can alter
test behaviour never passes as docs-only. The QA.md sentence quoted above is false. The named
examples are fixed, so this is major rather than a blocker. The chance of any one move hitting it is
lower, but the outcome is the same red `main`.

**Fix:**

1. Declare the glob readers in `changed_tests_map.yaml`, before the `*.md` rule. For example,
   `CLAUDE/*.md`, `docs/*.md` (fnmatch `*` crosses `/`) and the skill tree each map to
   `test_documented_commands_are_not_self_denied.py`, and `docs/*.md` also maps to
   `test_branch_install_gate_is_unadvertised.py`. Declared rules union with the reference mapping,
   so the `targeted` path picks them up too.
2. Pin it with a guard test. Scan `tests/` syntax trees for `.glob(`/`.rglob(` calls whose pattern
   ends in `.md` and whose base is derived from the repository root, plus `git ls-files`
   enumerations. Require each such test file to be named by a declared rule. Otherwise the next glob
   reader reopens the hole silently.
3. For tree-wide readers such as `test_repo_hygiene_check.py`, either declare them for any added or
   deleted path (`git diff --raw` status `A`/`D`), or treat an added or deleted document as
   `targeted` with those readers selected.
4. Reword QA.md:140-142 to state what the mapper sees: tests that name the file, the declared
   glob readers and the dependents.

### N2. MAJOR (R2 residual): `unmoved` and `--advance` are not bound to the head that lands

**Where:** `llm_qa.py`: `main_moved` (:1586), `start_batch` (:1497), `advance_batch` (:1655) and
`_uncertified` (:1636). Also `worktree_state`.

`main-moved` only compares `main` with the recorded base. It never asks whether the head it tells
you to fast-forward is the head that passed. Three ways through, all reproduced:

- **(a) The head moves after the gate** (`integ_late`). Run `--start`, then (the gate), then
  `git merge --no-ff m_code_change` (a late child). `main-moved` still gives `VERDICT: unmoved` and
  "git merge --ff-only integ_late, then push", exit 0. Meanwhile
  `llm_qa.py --read-only lint` on the same head exits 1, because the provenance already knows this
  head was never checked.
  - This is realistic in an agent team, where children finish at different times.
  - It also happens when a REJECT's fixed child is merged in again and STEP 1's `all` is not re-run.
- **(b) A second `--start` resets the base.** In `integ_delete_doc`, `m_code_change` was merged in,
  so `main-moved m_code_change` read `full-gate` (exit 4). Then `--start m_code_change` ran and
  printed "recorded". `main-moved m_code_change` then read `unmoved`, exit 0.
  - `start_batch` calls `update-ref` with no old value and no check that a base already exists.
  - A re-`--start` "to be safe" after merging code from `main` skips the full gate.
- **(c) An uncommitted tree certifies `--advance`** (`integ_delete_doc`). The committed merge fails
  `docs_qa` because a linked doc is deleted. The file was restored as an UNTRACKED copy. The doc
  tools then passed, `--advance` said "advanced to c8c0d9ed", and `main-moved` gave `unmoved`.
  `git ls-tree HEAD` still lacks the file, so the head that `--ff-only` lands fails `docs_qa`.
  - `worktree_state` digests the working tree, so the certification covers the uncommitted
    changes, while `--ff-only` lands only HEAD.
  - The same is true of the initial `all` gate.

**Fix:**

- Record the certified head. When `llm_qa.py all` passes on a CLEAN tree of a branch that has a base
  ref, and when `--advance` succeeds, write `refs/integration/<branch>/certified` = HEAD.
- `unmoved` then prints the fast-forward instruction only when `HEAD == certified` and the tree is
  clean. Otherwise it prints a new verdict, for example `head-moved` with its own exit code:
  "the integration head is not the one the gate passed: run `llm_qa.py all`".
- `--advance` refuses while the tree has tracked changes or untracked files that are not ignored.
- `--start` refuses when the base ref already exists, unless an explicit `--restart` is given, which
  is documented for a rebuilt batch only.
- Add tests for (a) to (c). Each is a few lines against the real-repository fixture that
  `test_llm_qa_main_moved.py` already has.

### N3. MINOR: the documented `case $?` branching does not survive `set -e`

**Where:** `CLAUDE/AgentTeam.md:1276-1287` (STEP 5) and :1780-1788 (Phase 5).

As written, with no prelude, the block branches correctly: exit 5 gave `BRANCH-recheck` and then
reached the end. The daemon's `R-BASH-SAFE-MODE-PRELUDE-MISSING` advisory asks for `set -euo pipefail`
on sequenced commands. With that prelude, `main-moved`'s exit 5 kills the script before `case`
runs: "shell exit 5", and no branch is printed. This fails safe, because no fast-forward happens,
but the documented branching is lost exactly when an agent follows the daemon's advice.

**Fix:** use `rc=0; ./scripts/qa/llm_qa.py main-moved || rc=$?; case $rc in … esac`.

### N4. MINOR (R7 residual): a double-quoted substitution hides a plainly named full run

The following are ALLOWED:

- `out="$(./scripts/qa/llm_qa.py all 2>&1)"; echo "$out"`
- `x="$(pytest tests)"`
- `echo "$(pytest tests)"`
- `` echo "`pytest tests`" ``
- `git commit -m "$(./scripts/qa/llm_qa.py all)"`

The unquoted `echo $(pytest tests)` is DENIED. HANDLER_REFERENCE lists "a substitution inside
double quotes" as a limit because "the program is only known once the shell has run it". That is
true of `$(which pytest)` but false here, where the program is written out.

Capturing QA output in a variable is an ordinary agent habit, so this is the most realistic escape
found.

**Fix:** recurse into `$(…)` and backticks found inside double-quoted words (the shared
`value_can_substitute` already detects them). Narrow the limit to a substitution in command
position.

### N5. MINOR (R7 residual): whole-suite spellings that are allowed and not listed as limits

- **Globs and braces.** `pytest tests/*`, `pytest tests/unit/*`, `pytest tests/{unit,integration}`
  and `pytest tests/unit/**/test_*.py` are all allowed. The word contains `/`, so it reads as narrow,
  but the shell expands it to the whole suite.
- **Stdin-fed or evaluated shells.** `eval 'pytest tests'`, `bash <<< 'pytest tests'`,
  `echo 'pytest tests' | bash` and `bash < <(echo pytest tests)` are all allowed.
- **Sourcing a declared script.** `source scripts/qa/run_tests.sh` and `. scripts/qa/run_tests.sh`
  are allowed, although `run_tests.sh` is a declared pattern.
- **Other spellings.** `python -c 'import pytest; pytest.main(["tests"])'`, `time -p pytest tests`
  (`-p` is then read as the command) and `builtin command pytest tests` are allowed.
- **ANSI-C quoting.** It is wider than the documented `llm_qa.py $'all'` limit.
  `echo $'a\'b' ; ./scripts/qa/llm_qa.py all` is ALLOWED: `shlex` reads `\'` as closing the quote,
  so the rest of the command becomes one quoted word.

**Fix:**

- Treat an operand containing unquoted `*?[{` as full when its literal prefix resolves to a full
  entry or one of its ancestors.
- Peel `eval`, `source`/`.` and `<<<`.
- Strip `time -p`.
- Pre-tokenise `$'…'` with its escape rules in the shared splitter.
- List as limits whatever is left, with reasons.

### N6. MINOR (R7 residual): whole-suite paths are judged from the event cwd, not the repository root

The `cd`-resolution fix places operands relative to the event's `cwd`. From `/workspace` (where a
teammate starts), all of these are ALLOWED:

- `pytest untracked/worktrees/worktree-plan-463-full-qa-gate/tests`;
- the same with `/tests/unit`;
- `pytest /workspace/untracked/worktrees/worktree-plan-463-full-qa-gate` (the absolute repo root;
  the absolute check skips the `.` entry);
- `cd <wt>/tests/unit/qa && pytest ../..`.

From `<wt>/tests`, `pytest unit` is also ALLOWED. `pytest /workspace/untracked/worktrees/<wt>/tests`
is correctly DENIED.

**Fix:** resolve each operand and find the repository or pytest rootdir containing it (the nearest
ancestor with `.git` or `pyproject.toml`). Judge `full_args` relative to that root, and treat the
root itself as full.

### N7. MINOR (R3 residual): the guidance test still misses prose that avoids its start words

`probe_463r4_setup_worktree.py` appended each line to the script and ran the test's own
`_full_runs`. These were MISSED:

- `echo "  Execute pytest tests before committing."`
- `echo "  Then use pytest tests/unit to check."`
- `echo "  Next, invoke python -m pytest tests."`
- `echo "  Finally: run the full suite (pytest)."`
- a `cat <<'EOF'` block containing "Run ./scripts/qa/llm_qa.py all before committing."
- `QA_CMD="./scripts/qa/llm_qa.py all"` followed by `echo "  Run $QA_CMD before committing."`

Candidates start only after `run`, a label colon, or a path-shaped word, so any other verb escapes.
The script prints no heredocs today, which is why this is minor.

**Fix:** use review 3's first option. Try `find_full_qa_invocation` on every suffix that starts at a
token equal to a declared pattern's `command` (or its basename). Scan `cat <<` bodies as printed
text too. Alternatively, run the script's final print block with a stubbed `WORKTREE_DIR` and judge
its real output.

### N8. MINOR (R7 residual): a false deny for `.` under a `cd`, and a stale QA.md rationale

- `cd tests/unit/qa && pytest .` and `cd tests/unit/qa && pytest ./` are DENIED. `_operand_is_full`
  tests `operand in full_args` before resolving, and `.` is literally in `full_args`.
  HANDLER_REFERENCE says operands are resolved from the directory the command runs in.
- `CLAUDE/QA.md:237-242` still says "the guard cannot see which directory an agent's shell is in".
  The guard now follows `cd`, so the bare-run rule should be stated as policy alone.

**Fix:** resolve `.` from `here` like any other operand, and refresh the QA.md paragraph.

### N9. NIT: `xargs` is not peeled at all

`xargs pytest tests` (explicit arguments, no stdin) is ALLOWED, as are `echo tests | xargs pytest`
and `find tests -name 'test_*.py' | xargs pytest`. The documented limit, "arguments supplied by
xargs", understates this.

**Fix:** peel `xargs` like a wrapper, or reword the limit to "any command run through `xargs`".

### N10. NIT: a heredoc delimiter with blanks, going to `cat`, is a false deny

`cat > n.txt <<' EOF'` and `<<'EOF X'` with the body `pytest tests` are DENIED, because the body is
not blanked. It fails closed. The same rows sent to `bash` are correctly denied.

### N11. NIT: leftovers in AgentTeam.md that contradict the new model

- **The parent's `-D` deletion.** STEP 8 (:1321) and the worked example still run
  `git branch -D worktree-plan-NNNNN`, which `R-GIT-BRANCH-FORCE-DELETE` denies (confirmed through
  the live chain). The line already exists on `main`. But in the new model the parent is
  fast-forwarded into `main`, so `git branch -d` succeeds. QA.md:163-164 now says "`-D` is not an
  agent's to run".
- **Dropping a child.** AgentTeam.md:264 says "rebuild the parent without it". QA.md:158-160 says to
  build a NEW integration branch from `main`. One of them should say how a plan's parent branch
  relates to a replacement branch.

### N12. NIT: base-ref housekeeping

- **The range check is exact-string.** It refuses `bc804523..m_tested_doc` although that is the
  same range. This is safe, and the printed command uses full SHAs. Resolving both ends to SHAs
  before comparing would remove the false refusal.
- **`refs/integration/<branch>/base` is never deleted after a batch lands**, so the refs accumulate.
- **Two branch names can collide.** A branch named `a` and one named `a/base` would collide
  directory-for-file in the ref namespace.

---

## Journal conflict resolution (00466): clean

- `git diff main...bc804523 -- CLAUDE/Plan/00466-niggles-ledger-sixteen/JOURNAL/` is 16 insertions,
  0 deletions, one file, and it has no `-` lines. The merge base `d71d180b` is on `main`.
- In the merge commit `4c37564a`, each parent's version of `00466-Journal-26-09-24.md` is an
  order-preserving subsequence of the result: nothing dropped, nothing reordered or modified.
- `git grep` finds no conflict markers anywhere in the tree at `bc804523`.
- **For the next sync:** `main` has appended 9 lines to that day-file since the merge, and the
  branch has appended its own. So the next `git merge main` conflicts in the same append region
  again.

## Shell parsing: 463's parser against 464's `utils/shell_lexer.py`

**How 463 parses.** `strip_inert_spans` (shared), then `split_unquoted` (shared), then `shlex.split`
per segment, then its own `_resolve`. It shares leaf helpers with the 464 lexer (`command_word`,
`DATA_SINKS`, `COMMAND_WRAPPERS`), but the tokenisers are independent.

**Against 464's known bug set:**

- **ANSI-C `$'…'`: the same hole, and wider than documented** (N5). It hides the rest of the
  command.
- **A heredoc delimiter with blanks: not the same hole.** 463 fails closed (N10). 464 lexes `<<'`
  plus the rest as one word and hides the body, which is a false allow for a guard.
- **A heredoc through `cat` and a pipe to a shell: 463 is correct and 464 is not.**
  `cat <<'EOF' | bash` and `| tee x | bash` are DENIED by 463. 464's `_bodies` drops the body
  because the receiver `cat` is a data sink, and never checks the pipe onward.

**Where 464 is better:**

- It returns double-quoted substitutions as `Nested`, which would close N4.
- It keeps operators, so `cd a || cd b` and subshell scope can be modelled. 463's `_changed_directory`
  treats every `cd` as sequential and persisting.

**Recommendation: do not adopt the 464 lexer at merge.** As it stands, it would regress 463 on the
pipe-to-shell and blank-delimiter rows and fix only N4. Plan it as a follow-up once 464's three
known bugs are fixed:

- Move `_invocations` onto `lex()`: words from `Word.raw`, `Nested` recursed at depth plus one, and
  `Operator` driving the `cd` scope.
- Adopt `probe_463r4_blocker.py` and `probe_463r4_lexer_compare.py` as the shared regression corpus
  for both handlers.
- Two tokenisers for one shell grammar is the drift `COMMAND_WRAPPERS` already had to be
  consolidated for.
- Until then, the cheapest local fix for N4 is to recurse into `$(…)` inside double-quoted words.

## Other checks (no finding)

- **Allowed commands.** Every new 463 procedure command is ALLOWED on the main thread by the live
  chain: `main-moved --start`/`--advance`, `git merge --no-edit main`,
  `cd /workspace && git merge --ff-only …`, `git reset --keep "$(git rev-parse …)"`,
  `git revert -m 1` and the STEP 5 block. The only denied line is the pre-existing `git branch -D`
  (N11).
- **A recheck over the wrong range.** A `targeted` recheck over another range passes QA 14/14, but
  `--advance` refuses: "changed_tests ran over …..23b6fa1a; run it with --range …..253eba21".
- **Rename and delete.** With `--no-renames`, a rename judges both paths. Both cases are caught by
  the `docs_qa` recheck (1 and 6 findings), and `--advance` refuses.

## Verdict

**CHANGES REQUIRED before merge: N1 and N2.**

- **N1.** R1's invariant still fails for tests that read documents by glob, and QA.md claims
  otherwise.
- **N2.** The `unmoved` verdict and `--advance` can bless a head that no gate passed: a late merge,
  a second `--start`, or an uncommitted fix.

Both have small, testable fixes, given above. N3 to N12 can follow as ledger items. The review 3
work is otherwise sound, and R4, R6 and R8 to R13 are verified.
