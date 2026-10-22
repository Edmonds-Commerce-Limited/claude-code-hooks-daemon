# Defence Before Fix report: a shipped script runs a bare python3/python (Plan 00546 Task 3.1, GitHub issue #130)

## Specification followed

DBF method specification 1.1.0, fetched (not vendored or cached) by the refresh script at the start of the task.

## Toolchain

The detector is the project's own QA script family: a Python checker in `scripts/qa/` (`check_bare_python_invocation.py`) that tokenises shell files, run through the project venv (`untracked/venv-*/bin/python`). Listing is `git ls-files` through the shared `scan_scope.walk_files`; the single-rule harness is the checker's own CLI (`--json`, `--path DIR`). It is registered in `scripts/qa/llm_qa.py` and `scripts/qa/run_all.sh`. The project had recorded no calibration, so the default sweep scope applied: first-party shell, generated and vendored code excluded.

## Defect and class

Originating instance: the upgrade's stale-venv cleanup step ran `python3 <paths.py> list-stale-venvs` with whatever `python3` was first on PATH. `daemon/paths.py` uses 3.10+ syntax, so on a host whose PATH python3 is older the step died with a traceback (see PLAN.md Problem section).

Class: "a shipped script runs a bare `python3`/`python` from PATH". Hazard: the interpreter is not the one the project resolved and version-checked, so code needing the minimum version fails (or silently does the wrong thing) on hosts where PATH python is older.

## Rule

- Detector: Python checker `scripts/qa/check_bare_python_invocation.py`, with a quote/heredoc/comment-aware shell tokenizer.
- Identifier: `bare-python-invocation` (meta rules `bare-python-allowlist-stale`, `bare-python-unreadable`). Message: "runs a bare python from PATH" plus the fix (use the resolved interpreter). Documented in `scripts/qa/qa-rules.json` and in `CLAUDE/QA.md` (Bare Python Invocation, with its width, scope, gaps and allowlist policy). The allowlist is `scripts/qa/bare-python-allowlist.json`, with `{file, line, occurrences, reason}` entries. Each entry pins a WHOLE line, indentation included, and an exact count: a new line, or a copy of an allowlisted line, is reported, and an unmet count fails as stale. The earlier substring `match` let a new `    python3 -c "import tomllib"` line in `init.sh` pass (review finding 2). That case is now a unit test against the real `init.sh` and the real entries.
- Width: the word `python`/`python3` as the COMMAND of a simple command (command position after `;`, `&&`, `||`, `|`, `(`, `{`, `$(`, backtick, `then`/`do`/`else`/`!`, and after `VAR=x`, `exec`, `env`, `sudo`, `nohup`, `timeout N`, `xargs`), and, after the widening (commit `ac99acf7b`), a bare name stored as a VALUE: `${VAR:-python3}`, `${VAR:=python3}`, `${VAR-python3}`, `${1:-python3}` (also nested and quoted) and `VAR=python3` (also after `local`, `export`, `declare`, `readonly`, `typeset`).
- Excluded as not carrying the hazard: `command -v python3`/`which` probes in the rule (these are listed as owner items below), arguments and `echo`/`printf` text, `${VAR:+python3}`, `python3.12`, resolved paths and `"$interpreter"`, comments, prose, heredoc bodies; files inside a plan folder (`CLAUDE/Plan/<folder>/...`, see Sweep for the proof); `tests/fixtures`, `untracked/worktrees`. Tests pin that `CLAUDE/UPGRADES/` and the plan tooling directly in `CLAUDE/Plan/` (`mkplan.bash`, `_planlib.inc.bash`) are still scanned.
- Next wider rule considered, not built: reading heredoc bodies that GENERATE agent-run shell (for example `.claude/skills/acceptance-test/invoke.sh` line 72, `TOTAL_TESTS=$(python3 -c ...)` inside a heredoc that writes a skill document). That instance was fixed with `jq`. Whether to build the rule is the owner's decision (OWNER-QUESTIONS.md Q3). The harness cannot tell a heredoc that generates shell from a data heredoc; that is a recorded gap, not a hazard sentence.

## Proof

Defence-red commit `ab1793dce`: the detector, its 68 unit tests and its registration, with the tree red by design. `untracked/venv-*/bin/python scripts/qa/check_bare_python_invocation.py --json` reported 41 instances there; the file-and-line list is in `261022-dbf-rule-sonnet.md`. The red did NOT fire on the originating instance. Phase 1 had already fixed the stale-venv cleanup on `main` (`62733426f`), so the fix came before the defence. That departs from the method's order, and it is recorded here. `scripts/upgrade_version.sh` was not among the 41; the widening caught it later. The originating shape (`python3 "$paths_script" list-stale-venvs` in a command substitution) is proven instead by the unit-test fixture `_ORIGINAL_INSTANCE` (`TestOriginalInstance`, `TestScan.test_finds_the_original_instance_in_a_shell_file`). The widened rule (`ac99acf7b`) has 15 positive value cases, 16 clean cases and line-number cases in `tests/unit/qa/test_check_bare_python_invocation.py`. The file now holds 116 tests, all passing.

## Independent search

Report: `261022-dbf-independent-search.md`. Text search (grep for `python3`/`python`) found forms reading the rule's tokenizer would not: probe-result forms (`command -v python3`), default arguments (`${VAR:-python3}`), an escaped heredoc line (invoke.sh:72) and Python files with `#!/usr/bin/env python3` shebangs. Reading found the command-position structure text search cannot judge (what is an argument versus a command). The rule initially missed value defaults, the `ensure_venv ... python3` argument and the invoke.sh heredoc line. The rule was widened for value defaults and assignments (`ac99acf7b`); the argument form and the heredoc line were fixed in the sweep (B1/B3). The search wins over the rule: the shebang and probe-result forms remain owner items (Q2). The first text pass and the reading shared one blind spot, the `${VAR:-python3}` defaults, so they count as a single technique; the second regex pass was the independent one. That the search ran without sight of the rule rests on dispatch records, not commits. The searcher and the rule writer were dispatched in the same turn, and the searcher was told the rule's file paths only so that it would keep out of them.

## Sweep and count

Scope: first-party shell (`.sh`, `.bash`, extensionless with a sh/bash shebang), git-visible, everywhere in the repository, generated and vendored code excluded (`tests/fixtures`, `untracked/worktrees`). Dev-only QA and CI scripts ARE in scope, because they run on developer hosts whose PATH python may be older. Counts: 41 at red; 34 after step A (QA/CI scripts fixed, plan folders excluded); 18 after B1 and B3; 11 after the final B3 fixes; 0 after allowlisting those 11 lines (8 entries, awaiting the owner, Q1).

**Plan-folder exclusion: proof.** The checker was run with and without the exclusion on this branch (`untracked/scratch/plan_excl.py`). With it: 0 violations, 149 files examined. Without it: 2 violations, 153 files examined.

- `CLAUDE/Plan/00266-ai-assisted-handler-decisions/prototype/dynamic-prompt-probe.sh:18`
- `CLAUDE/Plan/Completed/00154-daemon-performance-rust-vs-python-research/assets/bench_forwarder.sh:70`

Line 115 of `bench_forwarder.sh` is `python3` passed as an argument to `run_scenario`. The rule does not report it with or without the exclusion: it is the argument-to-a-wrapper gap listed under Q2. No file outside `CLAUDE/Plan/` names either script (`git grep`), except `CLAUDE/Performance/README.md`, which mentions the benchmark as prose. No install, upgrade, dispatch, hook, QA or CI step executes them. They are a prototype and a one-off benchmark. They ship inside the clone but nothing runs them, so they carry no hazard.

Building this proof found a real narrowing: the original exclusion covered all of `CLAUDE/Plan/`, which includes `mkplan.bash` and `_planlib.inc.bash`, which agents DO execute. It now covers only files inside a plan folder, and a test pins that both tooling files are scanned. Neither has a bare python today, so the scanned count rose from 147 to 149 with 0 violations.

**CI workflows: out of scope, with the reason.** `.github/workflows/qa.yml` has 7 bare `python` command lines (126, 171, 249, 338, 559, 621, 634) and 8 `$(command -v python)` probes (88, 130, 133, 293, 297, 563, 566, 623). They are spread over 5 jobs: `classify`, `targeted`, `qa`, `perf-sweep` and `daemon-load`; the `shell` job has none. Each line was checked against its job. Every one runs after that job's own `actions/setup-python@v5` step: `classify` 3.11, `targeted` 3.11, `qa` the 3.11/3.12/3.13 matrix, `perf-sweep` 3.11 and `daemon-load` 3.12. PATH `python` there IS the interpreter the job pinned, at or above `requires-python`, so the hazard cannot arise. Dockerfiles and Makefiles: the repository tracks no Makefile. Its only Dockerfile, `.claude/ccy/Dockerfile`, contains no `python` (`grep`).

## Fixes

Fixed by running the resolved interpreter (`${VENV_PYTHON}` / `resolve_existing_venv_python` / `PYTHON_BIN` from `scripts/lib/resolve_venv.sh`): the QA and CI scripts (`run_all.sh`, `run_lint.sh`, `run_shell_check.sh`, `run_tests.sh`, `run_type_check.sh`, `run_capture_corruption_check.sh`, `scripts/ci/*`), `health_check.sh`, `detect_location.sh`, `project_detection.sh`, `prerequisites.sh`, `venv-include.bash`, the v2 upgrade and migration scripts, and the acceptance-test `invoke.sh`. Each was read individually; the QA/CI scripts received the same change by pattern and were sampled. Where the resolver gives an empty interpreter the scripts fail loudly with a named message (the two migration scripts exit 1; `verification.sh` prints it and its checks FAIL); `detect_install_mode` fails loudly and its only caller (`detect_and_validate_project`) stops through `fail_fast`. `verification.sh`'s `PASS_COUNT`/`FAIL_COUNT` increments were rewritten as `X=$((X + 1))` (the `set -e` bug). The three shellcheck `disable=SC1090` lines in the v2 scripts became `# shellcheck source=scripts/lib/resolve_venv.sh`. A fourth, NEW `# shellcheck disable=SC1090` that this branch had added at `scripts/venv-include.bash:146` became `# shellcheck source=scripts/lib/python_discovery.sh` (review finding 9). `shellcheck -x` on that file is clean, and `check_inline_suppressions.py` reports 0 violations. `git diff main...HEAD` now adds no `shellcheck disable`, `noqa` or `type: ignore` outside plan prose. Stale entries were removed from `scripts/qa/error_hiding_exclusions.json`.

**Not fixed: 11 lines accepted on the allowlist, pending the owner.** There are 8 entries in `bare-python-allowlist.json`: 10 lines in `init.sh` and 1 in `install.sh`. Two of them (the `_detect_unsupported_python` version probe and the `install.py` bootstrap) are interpreter-finding or validating probes. The other six are hook hot-path JSON, transport and recovery snippets, written to a 3.8 floor and tested on 3.8 and 3.9. They are not interpreter probes. Accepting a known instance unfixed is the owner's decision, so all 8 are referred (OWNER-QUESTIONS.md Q1). The residual hazard, a PATH `python3` older than 3.8, is neither excluded nor tested. Release notes 014, 016 and 017 are in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Decisions referred to the owner

The full questions, with options and recommendations, are in `../OWNER-QUESTIONS.md`. Task 3.1 stays open until the owner rules. The rule is NARROWER than the independent search, so it is not "merged at full width". Whether it merges before Q2 is ruled on is itself the owner's call.

- **Q1, the allowlist:** 8 entries and 11 lines accepted unfixed (see Fixes). 0 fixed, 11 remaining. What stopped the fixing: these are hot-path or bootstrap code with no venv to run, and a rewrite has a latency cost to measure. Next to try: a 3.6 old-Python test, or rewriting the snippets.
- **Q2, the rule's scope:**
  - Shebangs: 54 files, about 5 run on a client (`install.py`, `scripts/debug_info.py`, `scripts/handler_status.py`, `core/error_response.py`, `scripts/audit_handler_config_keys.py`). 0 fixed. Stopped because a shebang needs a different detector. Next: a shebang rule for client-run entry points.
  - Probe results executed later: 4 sites (`scripts/bootstrap-self-install.sh:55`, `bin/hooks-daemon:193` and its template, the `.claude/ccy/claude-supervise` candidate loop). 0 fixed. Stopped on what a bootstrap may assume. Next: that ruling, then a probe-result rule.
  - The bare word as an argument to a wrapper that runs it, such as `run_scenario ... python3` in a plan benchmark: 0 found in scanned code.
  - CI: 15 lines carry no hazard (see Sweep), so they are recorded as out of scope rather than as a gap.
- **Q3, the next wider rule:** heredoc bodies that generate agent-run shell. The 1 instance found is fixed and 0 remain. Not built; the owner decides whether to build it.
- **Search ordering:** that the independent search came before the rule rests on dispatch records, not commits (see OWNER-QUESTIONS.md).

Engineering notes, not owner decisions:

- `verification.sh` hint text containing `python3 -c` (printed, not executed).
- `upgrade_version.sh` uses `GATE_PYTHON_FLOOR` as the build floor; split the two if they should differ.
- The resolver's multi-line trace prints before the `HOOKS_DAEMON_PYTHON` fallback in `detect_install_mode`.
- The `setup_worktree.sh` nesting guard prevents an end-to-end run; it is tested by function extraction.

## Permanence

The rule runs as the `bare_python_invocation` step of `llm_qa.py` (changed and full lists) and as step 25c of `run_all.sh`, so it blocks the commit gate. Through the entry point's detector run: `untracked/venv-*/bin/python scripts/qa/check_bare_python_invocation.py --json` passes with 149 files scanned. It is classified in `tests/integration/test_qa_walkers_examine_files_from_any_checkout.py` as a walker: it reports `files_scanned`, takes `--path`, examines files from a hostile checkout location, and fails on a missing or empty root. That file passes (116 passed).

**Evidence for the fixes (review finding 10).** `changed_tests` was not given a raised cap. The 207 test files it selects were instead run one file at a time; the result is in `untracked/scratch/find_hang.txt`.

- 204 passed.
- `tests/integration/test_qa_walkers_examine_files_from_any_checkout.py` failed, and is now fixed (116 passed).
- `tests/integration/test_provision_sh.py` passed (71 tests in 308 s).
- `tests/acceptance` is being confirmed by the coordinator.

The 1800 s cap is exceeded by the size of the selection (about 2300 s run in sequence), not by a hung test. `llm_qa.py changed` therefore has no recorded green from this task.

## Toolchain and detector gaps

The detector has no existing home in a shared shell-tokenizer library, so the checker carries its own small tokenizer. The shell-check harness has no way to tell shell that generates agent prompts from data heredocs (see Rule). `changed_tests` has a fixed 1800 s cap with no splitting for large selections.

## The original defect

Conventional fix: the stale-venv cleanup in the upgrade runs the resolved interpreter (or warns loudly) instead of PATH `python3` (Phase 1 of this plan, release note 014), and entry points refuse a Python below the minimum in one line (Phase 2, release note 016). The tests that reproduce the defect and now pass are those added in Phase 1 for the cleanup on a host whose `python3` is too old, and the Phase 2 entry point tests.
