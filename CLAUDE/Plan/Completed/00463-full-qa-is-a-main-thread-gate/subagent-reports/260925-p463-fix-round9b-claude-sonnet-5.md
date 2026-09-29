# Plan 00463 fix round after review 9, continued (Claude Sonnet 5)

**Scope.** Branch `worktree-plan-463-full-qa-gate`, resumed from a prior
fixer's uncommitted sink work after a session restart. Commit: `09617dc10`.

## What is done

**The sink (kept as inherited, lightly reviewed, unmodified in design):**

- `src/claude_code_hooks_daemon/qa/full_qa_lock.py` — host-wide full-QA lock
  under the git common dir, proven held via an inherited fd (checked through
  `/proc/self/fd` + a fresh-fd flock probe), never an env var.
- `src/claude_code_hooks_daemon/qa/full_qa_gate.py` — pytest plugin wired
  from `tests/conftest.py`; refuses a whole-suite-sized collection (>25% of
  test files) with no lock held. `scripts/qa/run_tests.sh` and
  `.github/workflows/qa.yml` acquire the lock before their whole-suite run.
- Verified `llm_qa.py all` and `run_all.sh` acquire the lock TRANSITIVELY
  (both invoke `run_tests.sh`) — no code change needed there.
- Verified `run_changed_tests.py` and `llm_qa.py changed --range/--base`
  invoke pytest directly, so they fall under the sink automatically once
  their selection is whole-suite-sized — no code change needed (resolves M1).
- `tests/unit/qa/test_full_qa_gate.py` / `test_full_qa_lock.py`: unit tests,
  including real subprocess pytest runs (bare, through a bash wrapper, and
  through a `python -c` exec wrapper) proving the sink refuses without the
  lock and permits with it, closing families B1/M6 as reproduced.
- `tests/integration/test_full_qa_gate_is_never_deadlocked.py`: pre-existing
  in the inherited state, left as-is.

**The Bash handler (`subagent_full_qa_blocker.py`), review 9's narrow items:**

- **B1 (blocker).** `_read_code`'s substitution/backtick branch now returns
  UNSEEN (deny) instead of ABSENT (silent allow) for a path it cannot
  resolve — matches review 9's exact direction. Paired this with adopting
  the prior fixer's `untracked/scratch/p463r9_script_dir_attempt.patch`
  (idiom resolution: `_evaluated_path`/`_path_substitution` for
  `cd&&pwd`/`dirname`/`realpath`/`readlink -f` of literals, and
  `_with_script_directory` for the `$(dirname "${BASH_SOURCE[0]}")` idiom),
  extended with a bare-`${BASH_SOURCE[0]}` substitution (for scripts that
  assign it to a variable before dirname'ing it) — WITHOUT this, the naive
  UNSEEN tightening denied ~62 of this repo's own everyday scripts (measured
  before/after against the corpus). Also narrowed the UNSEEN promotion to
  well-formed substitutions only (`$(` opener, or a backtick with a genuine
  non-adjacent closing backtick) after finding a markdown code-span
  (` `path` `) in a Python docstring was being mis-read as a malformed
  shell backtick and denying `check_doc_truth.py`.
- **m1.** `bash|sh -n` / `--noexec` now runs nothing (was denying
  `bash -n scripts/qa/run_tests.sh`).
- **m3.** `~+` added to the cwd-variable prefixes (bash's own `$PWD`).
- **m5.** New `_symlink_declared_name`/`_resolved_code_path`: a symlink to a
  declared runner is judged by the runner's PATTERN via its resolved target
  name, not by raw-scanning the link's own (possibly 100KB+) content.
- Did NOT touch B2, M2–M7 or n1–n4 — out of this round's scope per the
  brief ("do not keep widening the evasion parser"); the sink is the
  guarantee for what the handler still misses.

**m2 (a different Plan 00463 track, `scripts/qa/audit_error_hiding.py`):**
`_names_the_failure` is now an ALLOWLIST (`_reports_the_exception`): a yield
counts only when it carries the bound exception (`except ... as exc`), a
non-empty string/f-string, or a container/call that carries the exception.
Extended `_is_empty_iterable` for `range`, `map`, `itertools.chain`, a
generator expression and a ternary of two empty branches. All 12 of review
9's cited false-pass shapes now correctly flag `return-none-on-error`. Fixed
two existing sites this exposed in `subagent_full_qa_blocker.py`
(`_substituted_command`/`_code_of`'s `except ValueError` handlers) by
carrying `str(error)` into the yielded value.

**B1 residual (accepted, documented, not silently dropped):** a handful of
scripts resolve their own location via a plain `readlink` (uncomputable
without `-f`) inside a `while [ -L ... ]` loop, where the loop's
reassignment overwrites the resolvable pre-loop value (this handler's
variable tracking has no branch awareness). Affects `bin/hooks-daemon`
itself (and anything that shells out to it), `run_semgrep_check.sh`,
`run_canonical_callers_check.sh`, `install_version.sh`,
`dummy-client-repo.sh`, `bootstrap-self-install.sh`, `install/rollback.sh`,
`check_generated_doc_drift.py`. Pinned DENIED (not omitted) in
`_SCRIPTS_THAT_RUN_UNSEEN_CODE` / `_B1_RESIDUAL_UNSEEN` /
`TestBinHooksDaemonIsTheB1Residual`, documented in PLAN.md's "Round 9"
section. `bin/hooks-daemon` is more consequential than review 9's original
"4 accepted" list (it's the CLI entry point itself) — flagging this
explicitly since it wasn't in that list and a real fix needs branch-aware
variable tracking (which loop-body reassignment wins depends on whether the
loop's condition can be proven), which is genuine follow-up work, not
something I could close out this round.

**Docs:** PLAN.md gets a new "Round 9: the guarantee moves to the sink"
section (design + residual). `CLAUDE/QA.md`'s "Batched Integration Gate"
section now notes the coordinator's `llm_qa.py all` is the run holding the
lock. The handler's own `_RULE.verbose` text now says it is the first line,
not the guarantee.

## Verified

- `ruff check`, `mypy --strict`, `pyright`, `black --check`: clean on every
  touched file.
- `tests/unit/qa/test_audit_error_hiding.py::TestRealRepoSelfScan` (whole-
  repo error-hiding self-scan): clean.
- `tests/unit/handlers/pre_tool_use/test_subagent_full_qa_blocker.py` +
  `..._corpus.py`: 1228 passed, 1 pre-existing unrelated failure (below).
- `tests/unit/qa/` (whole dir) + the deadlock integration test: 1073 passed,
  1 pre-existing skip.
- Daemon restarted from this worktree; `bin/hooks-daemon status` reports
  RUNNING before the commit.

## NOT verified / left for the next round

- **M7's chain-timeout-must-not-be-an-allow check.** The brief asked me to
  "verify on your branch that a chain timeout is not an allow" and report if
  it is on the branch's base. I did not run this check — ran out of budget
  after the B1 investigation above. Needs a live daemon-chain timing probe
  (see review 9's own `probe_463r9_budget*.py` under
  `/workspace/untracked/scratch/`).
- **One pre-existing, unrelated test failure**:
  `TestThePytestOptionGrammar::test_every_value_option_of_the_running_pytest_is_known`
  fails on the UNMODIFIED module too (verified via a stashed-copy diff) —
  `--max-warnings`/`--report-chars` are missing from `PYTEST_VALUE_OPTIONS`,
  apparently from an installed pytest plugin's flags. Unrelated to this
  round; did not fix (scope).
- Did not queue a gate (per standing rules — the reviewer does that).
- B2, M2 (item 2 in the full_qa_blocker itself, oversized-text-runs-
  unread-code), M3–M7, n1–n4 from review 9 are all UNTOUCHED — the sink is
  the intended backstop for these, per the coordinator's design decision,
  but that has not been independently re-verified against each of those
  specific rows now that the sink exists.

## Handoff

SHA `09617dc10` on `worktree-plan-463-full-qa-gate`. Daemon restarted and
verified RUNNING. Next round should: (1) decide whether the B1 residual
list (especially `bin/hooks-daemon`) needs a real fix before merge or ships
as a documented, pinned limitation; (2) run M7's chain-timeout verification;
(3) have a fresh reviewer re-run the review 9 evasion corpus against this
branch to see how many of the 81 previously-allowed rows the sink now
closes for real, since that was the actual point of this round.
