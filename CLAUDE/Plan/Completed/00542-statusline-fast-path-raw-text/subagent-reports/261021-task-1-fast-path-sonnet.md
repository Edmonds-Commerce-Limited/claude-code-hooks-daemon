# Task 1 report: status-line fast path (issue #131, Plan 00542 Phase 1)

## What was built

- Daemon (`daemon/server.py`): `_raw_text_reply(response)` and a raw-text branch in `_answer_event`, Status socket only. A request carrying `hooks_daemon_raw_text: true` (`HookInputField.RAW_TEXT`, popped before dispatch) is answered with `text + "\n"`, or an EMPTY body for an error or no text. A request without the flag, and every other event, is answered as before. The field is documented in the Status input schema.
- Generator (`install/forwarder_generator.py`): `build_status_fast_path_block`, `strip_status_fast_path_block`, inserted above the `SCRIPT_DIR=` line of the status-line forwarder only, when `relay_enabled` or `nc_enabled`, with only the enabled clients built. Strip-then-reapply, like the relay guard. The events-dir lines and the checkout `BASH_SOURCE` guard were factored out of `build_relay_guard_block` into `_events_dir_lines` and `_checkout_guard_open` (DRY; same text, so `recorded_untracked_dir` / `recorded_project_root` still agree).
- Regenerated the tracked `.claude/hooks/status-line` the supported way: `python -m claude_code_hooks_daemon.install.forwarder_generator --project-root /workspace --hooks-dir <worktree>/.claude/hooks` (baked paths are the main checkout's `/workspace`; only status-line changed).
- Docs: `CLAUDE/Architecture/StatusLine.md` (new fast-path section); release note `CLAUDE/UPGRADES/UNRELEASED/release-notes/008-status-line-fast-path-raw-text.md`.

## Open points, as resolved

- Socket path without forks: the relay guard's own rule (`HOSTNAME`-derived suffix, or the baked fallback dir when the dir would be too long), `HOOKS_DAEMON_EVENTS_DIR` first. A wrong guess fails `-S` or the connect and falls through; nothing is printed unless a daemon of that path answered. The block only runs when `BASH_SOURCE` is under the baked checkout, so a worktree copy is inert.
- Config respected: relay client only if `relay_enabled` and the binary is executable (`HOOKS_DAEMON_RELAY_BINARY` honoured); nc only if `nc_enabled` and `HOOKS_DAEMON_NC_UNIX_CAPABLE=1` (env var, then the env file's capability line, read with `case` in a builtin loop, never sourced). Both off: no block at all, forwarder byte-identical to before. Why nc is off here was not investigated (owner config).
- Inert here: as configured (relay on, `untracked/bin/hooks-relay` missing, nc off) the fast path does nothing on this host (ledger N523). Measured below with the binary override only.
- Error-hiding guard: `read`'s status is handled with `|| _sf_rc=$?`; rc 1 is a normal EOF, above 1 falls through. No `/dev/null` on stderr.

## Measurements (worktree daemon up, 6 runs after one discarded warm-up, mean)

| Variant                                                                                                   | Wall          | CPU (user+sys) |
| --------------------------------------------------------------------------------------------------------- | ------------- | -------------- |
| Before (legacy forwarder)                                                                                 | 0.110-0.121 s | 0.084-0.092 s  |
| After, as configured here (relay binary absent: inert)                                                    | 0.108-0.111 s | 0.089 s        |
| After, `HOOKS_DAEMON_RELAY_BINARY=/workspace/untracked/relay-build/hooks-relay-x86_64-unknown-linux-musl` | 0.013-0.016 s | 0.005 s        |

Two measurement passes shown as ranges. The stdout of the fast and legacy runs started identically but was not byte-identical in my comparison (status text has time-varying segments); equality of the text is pinned by the daemon test (raw bytes equal the JSON `text` plus a newline).

## RED output (before implementation)

- `tests/unit/daemon/test_event_socket_status_raw_text.py`: `ImportError: cannot import name '_raw_text_reply' from 'claude_code_hooks_daemon.daemon.server'` (collection error).
- `tests/unit/install/test_forwarder_status_fast_path.py`: `12 failed, 15 passed` (the 15 passes are the inert and fall-through cases, which hold with no fast path; the 12 failures are the block text and the print-the-reply behaviours, e.g. `AttributeError: RAW_TEXT`).
- After implementation: those two files, 37 passed.

## Risks and notes

- A running daemon of a mismatched version answers the fast path; the legacy path's version handling (Plan 00488) runs only on fall-through. This is the same trade the relay guard makes for the other events.
- Trailing newlines of the status text are collapsed to one (`$(...)`); the python rung printed text plus one newline.
- Stdin replay on fall-through adds a trailing newline (here-string); the status payload is JSON, so this is harmless.
- Worktree venv: `tests/` needed `PYTHONPATH=<worktree>/src` to import this checkout's package; `./bin/hooks-daemon` restart in the worktree used its own venv.
- Two existing tests in `tests/unit/install/test_forwarder_generator.py` were adjusted to expect the status-line fast path (strip it before comparing).

## Review fix

Defect: the fast path printed any non-empty reply, so a daemon from before raw mode (answering with JSON during an upgrade, before its restart) would have its JSON printed on the status line.

- Added `RawTextReply.SENTINEL` (ASCII record separator, 0x1e) in `constants/protocol.py` (a separate class, because `test_input_fields_use_snake_case` requires every `HookInputField` value to be snake_case); `_raw_text_reply` now starts a text reply with it. Error and no-text replies stay empty.
- The generated block prints only a reply that starts with `$'\x1e'` (bash builtin test), strips it, and prints when the remainder is non-empty; JSON, no sentinel, or sentinel-only fall through with stdin replayed.
- Tests first (red: 9 failures, e.g. `'\x1eone | two\n' == 'one | two\n'` and the old-daemon `{"text": "x"}` reply printed instead of falling through), then green: 1952 passed over tests/unit/install, the raw-text daemon test and the two relay integration files.
- `.claude/hooks/status-line` regenerated with the forwarder_generator CLI (`--project-root /workspace`); StatusLine.md and release note 008 updated.

## Task 1.4: loud fast-path failures (owner ruling: no silent fallbacks)

- Generator (`build_status_fast_path_block`): one client only (relay if `relay_enabled`, else nc). A red one-line `_sf_loud` (ANSI 31, exit 0) for: relay binary missing, nc probe not 1 (names `HOOKS_DAEMON_NC_UNIX_CAPABLE=<value>`), nc not on PATH, relay exit 11 (`status timed out after 2s (daemon busy)`), any other non-zero client exit, empty reply, non-empty reply without the sentinel (`daemon older than its forwarder: run bin/hooks-daemon restart`), sentinel-only reply, `read` status above 1. The ONE hand-off, stdin replayed: no socket file, relay exit 10, nc exit 1 (and a payload that is not a JSON object, as before).
- Daemon (`_raw_text_reply`): error replies `sentinel + "⚠️ ERROR: <msg>"`, no text `sentinel + "⚠️ NO STATUS DATA"` (constants `RawTextReply.ERROR_PREFIX`, `NO_STATUS_DATA`); an empty reply is now a protocol fault.
- Exit-code facts used: relay `--no-fallback` 10 connect, 11 timeout, 12 I/O/oversize, 13 usage. nc: refused and missing socket both exit 1, a silent listener at `-w` exits 0 with an empty reply, so for nc the missing socket is decided by testing the socket file first and an empty reply is loud (timeout or protocol fault; nc cannot tell them apart).
- Missing-relay message names `bin/hooks-daemon transport on` (it provisions the binary, `ensure_relay_binary`). The nc message points at `bin/hooks-daemon transport status` (no separate probe command exists).
- Limitation: bash `read` returns 1 for EISDIR, EBADF, EIO and EOF alike and above 1 only for a timeout or bad `-u`, so the `read` fault branch cannot be driven by a real stdin; it is pinned by a generated-text test only.
- RED: 26 failed, 30 passed over the two touched test files (e.g. `_is_loud(...)` False for every loud row). GREEN: tests/unit/install and the raw-text daemon test, 1888 passed.
- Behaviour change: relay-and-nc both enabled no longer falls back from a missing relay to nc; relay wins and a missing binary is loud.
- Regenerated `.claude/hooks/status-line` (`--project-root /workspace`); StatusLine.md and release note 008 updated.
