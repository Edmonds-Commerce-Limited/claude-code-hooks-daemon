# Plan 00362 Task 2.5 — D8: raw_stdout forwarders daemon-down stdout

**Branch**: `agent-ae5316a815649bcd7-cf2fe7b2` · **Commit**: `adb82013` (fix), plus a
follow-up commit for the plan ticks and this report.

## Defect

`.claude/hooks/worktree-create` ended its `ensure_daemon` failure branch with
`emit_hook_error "WorktreeCreate" ...; exit 0`. Claude Code parses that hook's
stdout as the created worktree's absolute path, so a daemon that could not start
produced the literal path `/<cwd>/{...json...}`. `status-line` had the same
shape of problem (raw text on stdout, but `⚠️ DAEMON FAILED` was printed to the
raw channel rather than reported on stderr).

## Fix

- `src/claude_code_hooks_daemon/constants/events.py`: new
  `raw_stdout_bash_keys()`, derived from `EventIDMeta.raw_stdout` over the wired
  catalogue (today: `worktree-create`, `status-line`).
- `src/claude_code_hooks_daemon/install/forwarder_generator.py`: new
  `apply_raw_stdout_daemon_down(source, event_file_name)` replaces the first
  `if ! ensure_daemon; then ... fi` block of a raw_stdout event with a rendered
  branch that writes NOTHING to stdout, one `HOOKS DAEMON ERROR [daemon_startup_failed]: <Event> hook: ...` line to stderr, and `exit 1`.
  Idempotent; a JSON-decision event or a source with no stanza is returned
  unchanged. `generate_forwarder_content` applies it unconditionally (it is a
  correctness property of the event, not a transport option), so any stale
  deployed copy is corrected on the next regeneration.
- Tracked `.claude/hooks/worktree-create` and `.claude/hooks/status-line`
  regenerated with the deploy step's own module invocation
  (`python -m claude_code_hooks_daemon.install.forwarder_generator`). The
  worktree-create header comment that still claimed "all errors output JSON to
  stdout" was corrected by hand (it sits outside the generated stanza).
- Release callout: `CLAUDE/UPGRADES/UNRELEASED/release-notes/13-worktree-hook-daemon-down-stdout.md`.

## Tests (`tests/unit/install/test_forwarder_generator_raw_stdout.py`)

Drives the GENERATED forwarder under real `bash` against a stub `init.sh` whose
`ensure_daemon` fails and whose `emit_hook_error` prints JSON to stdout exactly as
the real one does. Parametrised over every `raw_stdout_bash_keys()` event:
stdout empty, exit non-zero, transport never reached, stderr carries
`daemon_startup_failed`. Control `pre-tool-use`: exit 0 and parseable error JSON
on stdout, unchanged. Also: transform idempotency, JSON-decision events and
stanza-less sources untouched, and the tracked forwarders are already in
generated form (so a client deploy that skips the Python step still ships the
right file).

RED confirmed before regeneration (only the two "tracked form" cases failed);
GREEN after.

## QA run (worktree venv `untracked/venv-...-py311-81c29529`)

- pytest over the new file plus `test_forwarder_generator*.py`,
  `test_forwarder_root_normalisation.py`, `test_relay_guard_eligibility_completeness.py`,
  `tests/unit/constants`, `test_forwarder_jq_free.py`, `test_relay_guard_fail_open.py`,
  `test_emit_hook_error_jqless.py`, `test_ci_passthrough.py`: 515 passed, 3 skipped.
- `ruff check` and `ruff format --check`: clean on the three touched Python files.
- `mypy --strict`: no issues in the three files.
- `shellcheck -x` on both regenerated forwarders: clean.
- Daemon NOT restarted (per instruction); no sed, no stash, no destructive git.

## Notes for the coordinator

- Running the generator with `--project-root <worktree>` rewrote all 29
  forwarders because the relay guard bakes the project root; re-running with
  `--project-root /workspace` (the recorded root, per Plan 00250 Task 2.4c)
  restored the 27 guard-carrying files byte-for-byte, leaving only the two
  raw_stdout files in the diff.
- `setup_worktree.sh` requires a branch name and creates a NEW worktree; for an
  existing agent worktree I reproduced its step 4 (`ensure_venv`) and then
  `uv sync --frozen --extra dev`, since `ensure_venv` alone does not install the
  dev extras (pytest/ruff/mypy).
- Plan 00189 Task 1.4 (full QA + daemon restart + live dogfood) remains open and
  belongs to the merge/release gate. The `init.sh` worktree-mode socket-error
  path already exits non-zero (Plan 00188), so no `init.sh` change was needed.
- Coordinator correction (second commit): the catalogue now carries a per-event
  `EventIDMeta.daemon_down_stdout` — empty for `WorktreeCreate` (stdout is a
  parsed value, nothing printed) and `⚠️ DAEMON FAILED` for `StatusLine`
  (stdout is a display line, the marker stays visible). The generator renders
  that text, the tracked forwarders were regenerated, and the test asserts
  each event's catalogue text plus named cases for both shapes; same checks
  re-run clean (517 passed, 3 skipped; ruff, mypy --strict, shellcheck).
