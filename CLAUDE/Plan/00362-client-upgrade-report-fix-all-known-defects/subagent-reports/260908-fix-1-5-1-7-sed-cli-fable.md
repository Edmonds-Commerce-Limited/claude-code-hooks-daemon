# Plan 00362 Tasks 1.5 and 1.7 — sed deny message, validate-config alias

Branch: `agent-af38229fa17e0719a-c28b0bde` (worktree
`/workspace/.claude/worktrees/agent-af38229fa17e0719a-c28b0bde`).

## Task 1.5 — `sed -n` deny is deliberate and says so

The rule is unchanged. What changed:

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/sed_blocker.py`
  - A `-n`/`-e` flag cluster with no `-i` (`_SED_STDOUT_ONLY_FLAG`) appends a
    note to the deny message: the deny is deliberate, `-n` and `-i` differ by
    one character, use `Read` with `offset`/`limit` or
    `awk 'NR>=a && NR<=b' file`. When the command carries an `N,Mp` range the
    awk line is filled in with those numbers. The note survives the terse
    (repeat-fire) ladder step. `sed -i` / `sed -ni` never get the note.
  - Class docstring and the `_executes_sed` / `_is_safe_readonly_command`
    docstrings no longer say read-only sed "is acceptable"; they state the
    four exemptions.
  - `get_claude_md()` exemption 1 now also names the awk alternative.
- `docs/guides/HANDLER_REFERENCE.md`: the sed_blocker entry's "not a blanket
  ban / read-only pipelines are allowed" text is replaced with the four
  exemptions (matching the CLAUDE.md block); the summary-table description
  no longer says read-only pipelines are allowed.
- Tests: `tests/unit/handlers/test_sed_blocker.py`,
  `TestStdoutOnlyFlagDenyIsDeliberate` (8 tests; RED before the change).

## Task 1.7 — `validate-config` alias, default path, skill-verb test

- `src/claude_code_hooks_daemon/daemon/cli.py`: `config-validate` gains
  `aliases=["validate-config"]`; `config_path` is `nargs="?"` and, when
  omitted, `cmd_config_validate` resolves the project via `get_project_path`
  and validates `.claude/hooks-daemon.yaml`. Module docstring updated.
- `src/claude_code_hooks_daemon/skills/hooks-daemon/SKILL.md` and the
  identical deployed copy `.claude/skills/hooks-daemon/SKILL.md`: the
  forwarding arm accepts `validate-config`; help text lists
  `config-validate [PATH]`.
- `docs/guides/TROUBLESHOOTING.md`: command table row mentions the alias and
  the default.
- New `tests/unit/daemon/test_cli_config_validate.py`: alias accepted and
  dispatches to the same command; omitted path defaults to the project
  config; explicit path still wins; every verb the SKILL.md `case` arms
  forward to `daemon-cli.sh` (literal or `"$SUBCOMMAND"` pass-through) and
  every `daemon-cli.sh` header example verb is accepted by the argparse
  parser (`<verb> --help` exits 0); deployed SKILL.md equals the package
  copy. Note: the repo's current SKILL.md already routed `config-validate`
  (the client's stale copy routed `validate-config`); the alias makes both
  spellings work end to end.

## Verification

- Setup: `scripts/setup_worktree.sh` requires a fresh branch name, so for
  this pre-existing worktree the venv was built with the same `ensure_venv`
  library call plus `uv sync --extra dev` (the plain call installs no
  pytest/ruff/mypy). Venv:
  `untracked/venv-workspace_claude_worktrees_agent-af3-3d75-py311-81c29529`,
  resolving the package from this worktree's `src/`.
- Touched suites (`test_cli_config_validate`, `test_sed_blocker`,
  `test_cli_main`, `test_cli_additional_commands`, `tests/unit/install`):
  1322 passed, 1 xfailed.
- Wide run (`tests/unit/handlers`, `tests/unit/daemon`, `tests/unit/install`):
  8700 passed, 2 skipped, 1 xfailed.
- `ruff check` and `ruff format --check` clean on all touched Python;
  `mypy --strict` clean on `sed_blocker.py`, `cli.py`, the new test.
- Daemon not restarted; no `sed` executed; no stash/destructive git.

## Release notes

`CLAUDE/UPGRADES/UNRELEASED/release-notes/13-sed-read-deny-explained-and-validate-config-alias.md`
(Plan 00362, audience: client projects). Number 13 was the next free one on
this branch; sibling agents may claim the same ordinal, so renumber on merge
if needed.

## Not done / for the coordinator

- PLAN.md task checkboxes for 1.5 and 1.7 are not ticked here (the plan file
  is shared across the parallel agents).
- The `-n` deny note keys on the flag cluster only; a `sed -n` inside a
  heredoc-written script gets the ordinary Write-branch message.
