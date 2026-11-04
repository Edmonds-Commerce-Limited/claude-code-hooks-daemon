# Plan 00563 Implementation Report

## What changed

- `src/claude_code_hooks_daemon/config_optimisation/claudemd_excludes.py` (new): `suggest_claudemd_excludes`, `git_worktree_paths`, `glob_to_regex` (moved from the integration test), `KNOWN_WORKTREE_ROOTS`.
- `src/claude_code_hooks_daemon/daemon/cli.py`: `cmd_optimise_checklist` appends the suggestion to the existing unscored `OPTIONAL (not scored):` lines. Text output only; the JSON output is unchanged.
- `tests/integration/test_worktree_claudemd_excludes.py`: now imports `glob_to_regex`; a new test pins `KNOWN_WORKTREE_ROOTS` to the roots the creators use.
- Skill doc `optimise.md`: new section in both the canonical `src/claude_code_hooks_daemon/skills/hooks-daemon/` copy and the deployed `.claude/skills/hooks-daemon/` copy (they were byte-identical before, and still are).
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/001-optimise-suggests-claudemd-excludes.md`.

## Behaviour

- Roots checked: `untracked/worktrees/` and `.claude/worktrees/` (only when they hold a subdirectory), plus the holding directory of every `git worktree list --porcelain` path inside the project root.
- Coverage is judged by matching a sample `<root>/example-worktree/CLAUDE.md` absolute path against every glob in `claudeMdExcludes` from `.claude/settings.json` and `.claude/settings.local.json`.
- Recommended file: `.claude/settings.local.json`. Silent when covered or when no worktree lives under the root.
- A malformed settings file is reported in the suggestion line (fail fast), not swallowed.
- Suggest only: nothing writes any setting. The optimise-invoke.sh instructions are unchanged, because the checklist output is already printed verbatim.

## Verification

- Red commit 5f7472110, green commit efe1c91cb.
- This worktree has no venv, so the main checkout's venv python was used with `PYTHONPATH=src`:
  `pytest tests/unit/config_optimisation/test_claudemd_excludes.py tests/unit/daemon/test_cli_optimise_checklist.py tests/integration/test_worktree_claudemd_excludes.py tests/integration/test_skill_surface_coherence.py --no-cov -q` gave 44 passed.
- `black --check`, `ruff check` and `mypy` on the touched files were clean.
- The full suite was not run, as instructed.
