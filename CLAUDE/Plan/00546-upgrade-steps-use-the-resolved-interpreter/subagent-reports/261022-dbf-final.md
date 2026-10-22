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
- Identifier: `bare-python-invocation` (meta rules `bare-python-allowlist-stale`, `bare-python-unreadable`). Message: "runs a bare python from PATH" plus the fix (use the resolved interpreter). Documented in `scripts/qa/qa-rules.json`; allowlist in `scripts/qa/bare-python-allowlist.json` (`{file, match, reason}` entries; an entry matching nothing fails).
- Width: the word `python`/`python3` as the COMMAND of a simple command (command position after `;`, `&&`, `||`, `|`, `(`, `{`, `$(`, backtick, `then`/`do`/`else`/`!`, and after `VAR=x`, `exec`, `env`, `sudo`, `nohup`, `timeout N`, `xargs`), and, after the widening (commit `ac99acf7b`), a bare name stored as a VALUE: `${VAR:-python3}`, `${VAR:=python3}`, `${VAR-python3}`, `${1:-python3}` (also nested and quoted) and `VAR=python3` (also after `local`, `export`, `declare`, `readonly`, `typeset`).
- Excluded as not carrying the hazard: `command -v python3`/`which` probes in the rule (these are listed as owner items below), arguments and `echo`/`printf` text, `${VAR:+python3}`, `python3.12`, resolved paths and `"$interpreter"`, comments, prose, heredoc bodies; `CLAUDE/Plan/` (plan prototypes and benchmarks never run on client hosts or by install, upgrade or dispatch; a test pins that `CLAUDE/UPGRADES/` is still scanned); `tests/fixtures`, `untracked/worktrees`.
- Next wider rule considered, not built: reading heredoc bodies that GENERATE agent-run shell (for example `.claude/skills/acceptance-test/invoke.sh` line 72, `TOTAL_TESTS=$(python3 -c ...)` inside a heredoc that writes a skill document). It was the only instance; it was fixed (with `jq`). A general reader would have to tell shell-that-generates-prompts from ordinary data heredocs, with a high false-positive risk, so it was not built.

## Proof

Defence-red commit `ab1793dce`: the detector, its 68 unit tests and its registration, with the tree red by design. `untracked/venv-*/bin/python scripts/qa/check_bare_python_invocation.py --json` reported 41 instances there, including the originating class (`scripts/upgrade_version.sh` and its siblings) and the file-and-line list in `261022-dbf-rule-sonnet.md`. The widened rule (`ac99acf7b`) has 15 positive value cases, 16 clean cases and line-number cases in `tests/unit/qa/test_check_bare_python_invocation.py` (now 103 tests, all passing).

## Independent search

Report: `261022-dbf-independent-search.md`. Text search (grep for `python3`/`python`) found forms reading the rule's tokenizer would not: probe-result forms (`command -v python3`), default arguments (`${VAR:-python3}`), an escaped heredoc line (invoke.sh:72) and Python files with `#!/usr/bin/env python3` shebangs. Reading found the command-position structure text search cannot judge (what is an argument versus a command). The rule initially missed value defaults, the `ensure_venv ... python3` argument and the invoke.sh heredoc line. The rule was widened for value defaults and assignments (`ac99acf7b`); the argument form and the heredoc line were fixed in the sweep (B1/B3). The search wins over the rule: the shebang and probe-result forms remain owner items.

## Sweep and count

Scope: first-party shell (`.sh`, `.bash`, extensionless with a sh/bash shebang), git-visible, everywhere in the repository, generated and vendored code excluded (`tests/fixtures`, `untracked/worktrees`; `CLAUDE/Plan/` excluded with the reason above, which excludes only code that never runs on client hosts or in install, upgrade or dispatch). Counts: 41 at red; 34 after step A (QA/CI scripts fixed, Plan dir excluded); 18 after B1 and B3; 11 after the final B3 fixes; 0 after allowlisting those 11 lines (8 allowlist entries).

## Fixes

Fixed by running the resolved interpreter (`${VENV_PYTHON}` / `resolve_existing_venv_python` / `PYTHON_BIN` from `scripts/lib/resolve_venv.sh`): the QA and CI scripts (`run_all.sh`, `run_lint.sh`, `run_shell_check.sh`, `run_tests.sh`, `run_type_check.sh`, `run_capture_corruption_check.sh`, `scripts/ci/*`), `health_check.sh`, `detect_location.sh`, `project_detection.sh`, `prerequisites.sh`, `venv-include.bash`, the v2 upgrade and migration scripts, and the acceptance-test `invoke.sh`. Each was read individually; the QA/CI scripts received the same change by pattern and were sampled. Where the resolver gives an empty interpreter the scripts fail loudly with a named message (the two migration scripts exit 1; `verification.sh` prints it and its checks FAIL); `detect_install_mode` fails loudly and its only caller (`detect_and_validate_project`) stops through `fail_fast`. `verification.sh`'s `PASS_COUNT`/`FAIL_COUNT` increments were rewritten as `X=$((X + 1))` (the `set -e` bug). The three shellcheck `disable=SC1090` lines became `# shellcheck source=scripts/lib/resolve_venv.sh`. Stale entries were removed from `scripts/qa/error_hiding_exclusions.json`. Allowlisted (8 entries, 11 lines, each with a reason in `bare-python-allowlist.json`): the B2 forwarder snippets and interpreter-finding probes that run before any venv exists. No instance was satisfied by suppressing the rule or leaving the hazard in place; `check_inline_suppressions.py` reports 0 violations. Release notes 014, 016 and 017 are in `CLAUDE/UPGRADES/UNRELEASED/release-notes/`.

## Decisions referred to the owner

Left unchanged and not counted by the rule (fixed 0 of each, remaining as listed). They are outside the practitioner's authority because each is an interpreter-FINDING bootstrap or a shape the rule deliberately does not cover; the rule is merged at full width, not weakened.

- Probe-result forms: `scripts/bootstrap-self-install.sh:55` (`command -v python3`), `bin/hooks-daemon:193` and its template, the `.claude/ccy/claude-supervise` candidate loop.
- 54 Python files with `#!/usr/bin/env python3` shebangs; about 5 are plausibly run on a client (`install.py`, `scripts/debug_info.py`, `scripts/handler_status.py`, `core/error_response.py`, `scripts/audit_handler_config_keys.py`). A shebang detector is a separate rule.
- `.github/workflows/qa.yml` `python`/`command -v python` lines.
- `verification.sh` hint text containing `python3 -c` (printed, not executed).
- `upgrade_version.sh` uses `GATE_PYTHON_FLOOR` as the build floor; split the two if they should differ.
- The resolver's multi-line trace prints before the `HOOKS_DAEMON_PYTHON` fallback in `detect_install_mode`.
- The `setup_worktree.sh` nesting guard prevents an end-to-end run; it is tested by function extraction.

Next to try: a shebang rule for the 5 client-run Python entry points; fixing the probe-result forms needs a decision on what the bootstrap may assume.

## Permanence

The rule runs as the `bare_python_invocation` step of `llm_qa.py` (changed and full lists) and as step 25c of `run_all.sh`, so it blocks the commit gate. Through the entry point's detector run: `untracked/venv-*/bin/python scripts/qa/check_bare_python_invocation.py --json` passes with 147 files scanned. It is classified in `tests/integration/test_qa_walkers_examine_files_from_any_checkout.py` as a walker (reports `files_scanned`, takes `--path`, examines files from a hostile checkout location, fails on a missing or empty root); that file passes (116 passed). Targeted per-file QA over the 207 mapped test files: 204 pass, and two files are only slow (the coordinator is confirming). `changed_tests` timed out at its 1800 s cap because the selection (207 files, about 2300 s sequential) exceeds the cap, not because a test hangs; the coordinator handles this. `llm_qa.py changed` was therefore not run to a recorded green by this task.

## Toolchain and detector gaps

The detector has no existing home in a shared shell-tokenizer library, so the checker carries its own small tokenizer. The shell-check harness has no way to tell shell that generates agent prompts from data heredocs (see Rule). `changed_tests` has a fixed 1800 s cap with no splitting for large selections.

## The original defect

Conventional fix: the stale-venv cleanup in the upgrade runs the resolved interpreter (or warns loudly) instead of PATH `python3` (Phase 1 of this plan, release note 014), and entry points refuse a Python below the minimum in one line (Phase 2, release note 016). The tests that reproduce the defect and now pass are those added in Phase 1 for the cleanup on a host whose `python3` is too old, and the Phase 2 entry point tests.
