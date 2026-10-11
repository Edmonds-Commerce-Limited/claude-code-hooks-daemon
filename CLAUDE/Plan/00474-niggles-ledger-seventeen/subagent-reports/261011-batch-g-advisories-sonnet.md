# Batch G: advisories (N340, N353, N367, N369)

Branch `agent-a5313785be3bc54d9-56f41b13`, code commit c213595a8.

## N340 fixed

Root cause: `daemon_docs_guard.py` matched the segment `.claude/hooks-daemon/CLAUDE/` with no install-mode check. In
self-install mode that path is this repository's own CLAUDE/ tree.

Fix: `matches()` returns False once the path matches and `self_install_reader()` (default
`ProjectContext.self_install_mode`, the same seam `issue_filing_gate.py:193` uses) is true. An unresolvable context
fails closed to client install (advisory kept). Tests: `TestSelfInstallStandsDown` in
`tests/unit/handlers/pre_tool_use/test_daemon_docs_guard.py` (self-install no match; client install still matches;
RuntimeError fails closed). The existing fixture is pinned to client install.

## N353 fixed

Root cause: pattern `\bout of scope\b` matched whatever the sentence cited.

Fix: in `dismissive_language.py`, the `out_of_scope` category is scanned on text with sentences removed that cite
a threat model, Non-Goals, owner ruling/decision, `per owner/ruling/plan`, or a limb. Judged per sentence, so a reason in
another sentence does not excuse a bare deflection. Still advisory. Tests: `TestOutOfScopeGroundedInACitedReason`
(4 grounded phrasings not firing; bare, cross-sentence and other-category cases still firing).

## N369 verified, NOT stale (left Open, evidence recorded)

Ran `tests/integration/test_forwarder_socket_stdin.py` from this worktree: 1 failed, 6 passed. The Stop test fails with
"Daemon startup timeout" and "Daemon already running (PID ...)", which is main's daemon (`--project-root /workspace`).
`.claude/hooks-daemon.env` here is a symlink to `/workspace/.claude/hooks-daemon.env`
(`HOOKS_DAEMON_ROOT_DIR="/workspace"`); `init.sh:1213-1220` sources it over any inherited value, so the test cannot
override it through the subprocess env. `setup_worktree.sh:380-395` writes a correct file, so worktrees it builds are
likely fine (not run). Remaining fix is in harness worktree creation or a test skip; not small and clear.

## N367 fixed (recipe); second bullet is a lock-bump precondition

All documented installs already use the lock (`CONTRIBUTING.md:21`, `setup_worktree.sh`). The one off-lock recipe left
in the repository was the missing-semgrep remedy at `scripts/qa/run_semgrep_check.sh:49`; it now prints
`uv sync --frozen --all-extras`, pinned by `TestMissingSemgrepRemedyIsLockMatched`. The coordinator's own recipe lives
outside the repository. `uv.lock` pins pytest 9.0.3 and ruff 0.15.11, so the ruff 0.16 / pytest 9.1 failures cannot
reproduce today.

## Tests and QA

Targeted tests (dismissive, daemon-docs-guard): 61 passed. Red phase was written first but not separately run (no
way to run the pre-change tree without stashing); the true-positive cases are kept as tests. black clean on all
changed Python. `llm_qa.py changed --allow-unmapped`: see the coordinator note in the reply (the worktree has no venv
of its own, so it was run with `HOOKS_DAEMON_VENV_PATH` pointing at main's venv).
