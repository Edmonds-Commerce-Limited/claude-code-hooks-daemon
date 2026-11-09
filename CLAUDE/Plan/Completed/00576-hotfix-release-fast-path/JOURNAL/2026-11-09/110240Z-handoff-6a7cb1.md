## 11:02 · handoff · —   — WIP handoff

WIP handoff (the session is moving hosts). Branch `hotfix-release-fast-path`, off origin/main 36fe86b40, pushed.

DONE (committed; Tasks 1.1-3.4 ticked in PLAN.md):

- Item 2, advisories never fail: `scripts/qa/run_corpus_qa.py` now passes and exits 0 unless a finding is block-severity
  or has no readable severity (`is_failing`). `CLAUDE/QA.md` matches. Tests are in `tests/unit/qa/test_run_corpus_qa.py`
  (advise-only passes and exits 0, block fails, unknown severity fails). RED was observed first.
- Item 3, stale CI: `release-gate.yml` ALREADY had `concurrency: release-gate-<PR or ref>, cancel-in-progress: true`
  (Plan 00476), so it was not edited. `TestASupersededRunIsCancelled` in `tests/unit/qa/test_release_gate_layout.py`
  now pins it.
- Item 1, hotfix mode: `.claude/skills/release/invoke.sh` takes arguments in any order (`hotfix`, `accept-wip`, a
  version or bump). In hotfix mode it uses patch by default, refuses major/minor (exit 2), passes `--accept`, and prints
  the fast-path block, which asks for `"mode": "hotfix"`. `SKILL.md` usage is updated. `RELEASING.md` has the new
  section "## Hotfix fast path" (step table), the `mode` field in "The release state file", and pointers from Quick
  Release and Pipeline Overview. `release_blocker.py` names the mode in its deny message: hotfix points at the fast path
  and scopes acceptance to 12.0 plus targeted tests, and an unknown mode is named and falls back to standard. Tests are
  in `tests/integration/test_release_skill_hotfix_mode.py` and `.claude/project-handlers/stop/test_release_blocker.py`
  (`TestTheReleaseModeIsNamed`).
- Callout `CLAUDE/UPGRADES/UNRELEASED/release-notes/013-hotfix-release-fast-path.md`. If another branch claims 013
  first, renumber it.

TEST STATUS: the 41 changed-file tests pass. Project-handler tests pass (300); run them with
`<venv>/bin/python -m claude_code_hooks_daemon.daemon.cli --project-root <worktree> test-project-handlers`. ruff and black
are clean on the changed files.

PARTIAL TARGETED QA: the run was killed for the host move. Results so far:

- Passed: docs_qa, plan_qa (1 advise finding, journal freshness on 00560, now a pass by design), lint, type_check,
  pyright, eacces_safe and error_hiding.
- format: black reformatted one missing space, fixed in commit 2.
- magic_values: flagged `timeout=30` in the new invoke test. Fixed by using `Timeout.REQUEST_DEFAULT` in the WIP commit.
- Not reached: the rest, including shell_check on invoke.sh. A manual `shellcheck` on invoke.sh was clean.

NEXT STEPS:

1. Provision a venv in the new worktree. `setup_worktree.sh` only creates new worktrees, so source its helpers instead:
   `scripts/install/{output,mode_guard,python_fingerprint,venv,venv_resolver}.sh` and `scripts/lib/python_discovery.sh`,
   then `ensure_venv <wt> v<version> <python>` and `uv sync --frozen --all-extras` into it.
2. Run `FULL_QA_LOCK_WAIT_SECONDS=3600 <venv python> ./scripts/qa/llm_qa.py changed --range origin/main..HEAD --allow-unmapped`
   and fix anything it reports.
3. Tick Task 4.1, write a journal entry, push, and run
   `gh pr create --base main --head hotfix-release-fast-path --title "Hotfix release fast path"`.
   Do not merge: the coordinator merges after the in-flight v3.73.1 release.

NOTHING is half-edited.
