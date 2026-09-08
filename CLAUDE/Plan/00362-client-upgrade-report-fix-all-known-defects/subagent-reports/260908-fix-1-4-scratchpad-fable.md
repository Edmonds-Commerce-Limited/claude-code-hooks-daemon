# Task 1.4 — project_containment allows the harness scratchpad

**Branch**: `agent-a23feb5b67ac1c6fe-0c41c8c4` (worktree
`/workspace/.claude/worktrees/agent-a23feb5b67ac1c6fe-0c41c8c4`)

## How the scratchpad is derived

The CLI binary (`@anthropic-ai/claude-code` 2.1.263, `bin/claude.exe`) builds
every hook payload as
`{session_id, transcript_path, cwd, scratchpad_dir: PI(session_id) ?? undefined, ...}`,
where `PI()` is `join(<claude temp dir>, <session id>, "scratchpad")`. So the
harness NAMES the directory in the payload itself; no environment variable
carries it (the only related env vars are `CLAUDE_TMPDIR` /
`CLAUDE_CODE_TMPDIR`, which override the temp root, not the scratchpad).
The handler therefore reads `hook_input["scratchpad_dir"]`
(`HookInputField.SCRATCHPAD_DIR`, new constant in `constants/protocol.py`)
and allows a write whose target resolves at or under it. That is the robust
derivation the task asked for: nothing is inferred from a `/tmp/claude-<uid>/`
shape, an absent field grants nothing, and an empty or relative value is
treated as "no scratchpad".

Scope chosen: exactly the `scratchpad` directory, not its parent session
directory. The session dir also holds the harness's own `tasks/` tree, which
the agent is never told to write into, so opening it would be an assumed
exemption rather than a declared one (Plan 00333 Decision 3).

Not verified from a captured live payload: no capture under
`/workspace/untracked/` contained the field, and capturing one would have
meant touching the main checkout's daemon config, which is out of bounds for
a worktree agent. The evidence is the binary's payload builder quoted above.

## Changes

- `src/claude_code_hooks_daemon/handlers/pre_tool_use/project_containment.py`:
  `_harness_scratchpad()` reads the payload field; `_is_permitted()` takes it
  as a second allowance beside the Claude home; the deny message adds a
  `THROWAWAY ONLY: <scratchpad>/` line when one exists; the rule's verbose
  text no longer claims "there is no throwaway location"; `get_claude_md()`
  gains a paragraph saying the scratchpad is allowed, why, that it is wiped
  with the session, and that anything durable still belongs in
  `untracked/scratch/`.
- `src/claude_code_hooks_daemon/constants/protocol.py`: `SCRATCHPAD_DIR`.
- `tests/unit/handlers/pre_tool_use/test_project_containment.py`: new
  `TestTheHarnessScratchpadIsAllowed` (10 cases: allow inside, nested, Bash
  redirect; deny session sibling `tasks/`, another session's scratchpad,
  prefix sibling, same path without the field, empty/relative field, plain
  `/tmp`; denial names both places) plus a guidance test. RED first (5
  failed), GREEN after.
- `docs/guides/HANDLER_REFERENCE.md`: one paragraph in the handler section.
- `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-containment-allows-the-session-scratchpad.md`.

Acceptance tests unchanged: the deny probe targets
`<tmp>/acceptance-test-containment/`, which is not a scratchpad, so its shape
still holds. A scratchpad ALLOW acceptance test was not added because the
directory is only known at event time, not at playbook-generation time.

## QA run (worktree venv, built with `uv sync --frozen --all-groups`)

- `tests/unit/handlers` (6005 passed), plus `tests/unit/constants` and the
  integration tests that mention containment / generated docs / release
  notes: all green.
- `ruff check`, `ruff format --check`, `mypy --strict` on the touched files:
  clean. `scripts/qa/check_handler_reference.py`: no violations.
- Daemon NOT restarted (per instruction); the running daemon still enforces
  the old behaviour until it is.

Note on `./scripts/setup_worktree.sh`: it takes a branch name and CREATES a
worktree, so it cannot be run inside an already-provisioned agent worktree;
the venv was built with the same `uv sync --frozen` its `ensure_venv` helper
uses, at `<worktree>/.venv`, and verified to import the worktree's `src/`.
